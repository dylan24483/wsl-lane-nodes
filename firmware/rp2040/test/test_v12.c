/*
 * Host unit test for the v1.2 rev-D tap features (remediation spec R3 — closes C2).
 *
 * THE C2 GATE LIVES HERE: Codex's finding was that "firmware never outputs on
 * GP16-19" was accidental non-use, not an enforced invariant. This binary:
 *   (1) DIRECTION-INVARIANT TEST — drives the full firmware state machine through
 *       init + normal operation + every fault path + dumps, with the mock SDK
 *       recording EVERY gpio_set_dir(OUT)/gpio_put() per pin, and FAILS if
 *       GP16-19 (or GP26) ever appear in an output-direction or output-write
 *       call. Any future code path that drives a tap pin fails this build.
 *   (2) TAMPER TEST — corrupts the mock OE register mid-run and asserts
 *       tap_assert_input_only() trips (latch_fault "tap_dir" -> RP_OK refused).
 * plus the R3.1 inverted decode, the R3.3 noinit ring (capture order, wraparound,
 * reboot persistence + epoch, power-loss zeroing, TAPDUMP/TAPCLR, cause
 * classification, dump starvation guard), the R3.4 ADC window, the IRQ storm
 * guard, and the RPOK cross-check (warn-only by default — enforcement stays
 * compiled OFF, same posture as the v1.1 flags).
 *
 * Build + run (from firmware/rp2040/):
 *   gcc -std=c11 -Wall -Wextra -Werror -I test -I test/stubs test/test_v12.c -o test/test_v12.exe
 *   ./test/test_v12.exe          # exit 0 = all checks passed
 */
#include "mock_pico.h"
#include "mock_impl.h"      /* shared mock state + bodies + harness helpers */
#include <stdio.h>
#include <string.h>

/* ---- pull in the firmware under test (rename its main) -------------------- */
#define main fw_main
#include "../main.c"
#undef main

static void pump(void) { txr_drain(); }

static int checks = 0, fails = 0;
#define CHECK(cond, msg) do { checks++; if (!(cond)) { fails++; printf("  FAIL: %s\n", msg); } \
                              else { printf("  ok:   %s\n", msg); } } while (0)

/* simulate one raw edge on a tap pin the way silicon does: pad level changes,
 * then the registered IRQ callback fires with the matching edge event.
 * REMEMBER the inversion: raw fall = observed-net RISE (level 1). */
static void tap_edge_sim(uint pin, int new_raw) {
    mock_gpio_in[pin] = new_raw;
    if (mock_irq_cb)
        mock_irq_cb(pin, new_raw ? GPIO_IRQ_EDGE_RISE : GPIO_IRQ_EDGE_FALL);
}

/* drive one full debounced cam edge (as in test_v11.c) */
static void cam_edge(uint pin, int level) {
    mock_gpio_in[pin] = level;
    scan_inputs();
    advance_us(DEBOUNCE_CAM_US + 1);
    scan_inputs();
}

/* clean baseline incl. a COLD tap ring (magic invalidated -> epoch 1, pre 0) */
static void reset_clean(void) {
    all_idle(); mock_us += 5000000ull;
    memset(&tap_ring, 0, sizeof tap_ring);     /* cold power-up: garbage/zero magic */
    tap_boot_init(false);
    init_inputs(); init_camstops();
    motors_all_stop();
    fault_latched = false; fault_code[0] = 0;
    rx_discard = false; llen = 0;
    mock_rx_head = mock_rx_tail = 0;
    txr_head = txr_tail = 0; txr_drops = 0; tx_reset(); mock_uart_writable = true;
    booted_done = true;
    rp_ok_state = true; mock_gpio_out[PIN_RP_OK] = 1;
    dump_n = dump_pos = 0; dump_end_pending = false;
    rpok_mism_strikes = 0; last_tapwarn_ms = 0; tapwarn_ever = false;
    adc_v5_have = false; adc_v5_mv = adc_v5_min = adc_v5_max = 0;
    /* taps idle: raw HIGH = observed LOW everywhere (matches all_idle) */
}

int main(void) {
    printf("== RP2040 firmware v1.2 tap/ring/ADC test (rev-D remediation R3 / C2) ==\n");

    /* ---- pre: version + compiled-off posture ----------------------------- */
    printf("[pre] version / default posture\n");
    CHECK(strstr(FW_VERSION, "v1.2") != NULL, "FW_VERSION bumped to v1.2");
    CHECK(TAP_RPOK_FAULT_ENABLED == 0, "RPOK-mismatch FAULT escalation compiled OFF by default");
    CHECK(CAM_SA_STOP_ENABLED == 0 && CAM_TA1_STOP_ENABLED == 0
          && INTERLOCK_ECHO_ENABLED == 0 && MOTION_NO_RUN_ENABLED == 0,
          "v1.1 enforcement flags still default OFF in v1.2");

    /* ---- A: tap_init choke point sets exactly the R3.1 pin table --------- */
    printf("[A] tap_init choke point\n");
    reset_clean();
    tap_init();
    {
        int ok_dir = 1, ok_fn = 1, ok_irq = 1;
        for (uint i = 0; i < N_TAPS; i++) {
            if (mock_gpio_dir[tap_pins[i]] != GPIO_IN) ok_dir = 0;
            if (mock_gpio_funcsel[tap_pins[i]] != GPIO_FUNC_SIO) ok_fn = 0;
            if (mock_irq_mask[tap_pins[i]] != (GPIO_IRQ_EDGE_FALL | GPIO_IRQ_EDGE_RISE)) ok_irq = 0;
        }
        CHECK(ok_dir, "GP16-19 all input direction");
        CHECK(ok_fn,  "GP16-19 all SIO function");
        CHECK(ok_irq, "GP16-19 all both-edge IRQs enabled");
    }
    CHECK(mock_gpio_funcsel[PIN_ADC_VCC5] == GPIO_FUNC_NULL, "GP26 handed to the ADC (function NULL)");
    CHECK(mock_adc_inited == 1 && mock_adc_selected == (int)ADC_VCC5_INPUT, "ADC inited + input 0 selected");
    CHECK(mock_irq_cb != 0, "shared tap IRQ callback registered");
    CHECK(tap_assert_input_only(), "invariant readback passes after tap_init");
    CHECK(!fault_latched, "no fault from a clean init");

    /* ---- B: THE C2 DIRECTION-INVARIANT TEST ------------------------------ */
    /* Full firmware exercise. The mock records every output-direction/write
     * call per pin; taps must never appear in one — on ANY path. */
    printf("[B] direction invariant across init + operation + faults\n");
    reset_clean();
    memset(mock_dir_out_calls, 0, sizeof mock_dir_out_calls);
    memset(mock_put_calls, 0, sizeof mock_put_calls);
    tap_init();
    /* normal operation */
    rx_feed("RUN S\n"); poll_uart();
    cam_edge(PIN_SA, 0); cam_edge(PIN_SA, 1);
    rx_feed("STOP S\n"); poll_uart();
    mock_gpio_in[PIN_DIELL_L] = 0; scan_inputs();
    advance_us(DEBOUNCE_DIELL_US + 1); scan_inputs();          /* ball */
    tap_edge_sim(PIN_TAP_KICK, 0); tap_edge_sim(PIN_TAP_KICK, 1);   /* tap edges */
    supervise(); emit_hb(); tap_hb_tick(); tap_service(); pump();
    /* fault paths: motion timeout -> CLEAR; chatter */
    rx_feed("RUN T\n"); poll_uart();
    advance_ms(MAX_MOTION_MS + 5); supervise();
    CHECK(fault_latched, "setup: motion_timeout latched");
    rx_feed("CLEAR\n"); poll_uart(); supervise();
    for (int i = 1; i <= 24 && !fault_latched; i++) {
        mock_gpio_in[PIN_SB] = (i & 1) ? 0 : 1;
        scan_inputs(); advance_us(DEBOUNCE_CAM_US + 10); scan_inputs();
    }
    CHECK(fault_latched, "setup: chatter latched");
    rx_feed("CLEAR\n"); poll_uart(); supervise();
    /* tap commands */
    rx_feed("TAPDUMP\n"); poll_uart(); tap_service(); pump();
    rx_feed("TAPCLR\n"); poll_uart(); pump();
    /* heartbeat ticks incl. the RPOK cross-check mismatch path */
    mock_gpio_in[PIN_TAP_RPOK] = 1;   /* observed LOW vs rp_ok_state true = mismatch */
    tap_hb_tick(); tap_hb_tick(); tap_hb_tick(); pump();
    {
        int tap_out = 0;
        for (uint i = 0; i < N_TAPS; i++)
            tap_out += mock_dir_out_calls[tap_pins[i]] + mock_put_calls[tap_pins[i]];
        tap_out += mock_dir_out_calls[PIN_ADC_VCC5] + mock_put_calls[PIN_ADC_VCC5];
        CHECK(tap_out == 0,
              "GP16-19 + GP26 NEVER set output or written on any exercised path (C2 gate)");
        CHECK(mock_put_calls[PIN_RP_OK] > 0,
              "sanity: the instrumentation DOES see GP2 writes (recorder is live)");
    }

    /* ---- C: tamper test — OE corruption trips the enforced invariant ----- */
    printf("[C] register-tamper -> tap_dir fault\n");
    reset_clean(); tap_init();
    mock_gpio_dir[PIN_TAP_KICK] = 1;            /* simulate rogue OE flip / latchup */
    CHECK(!tap_assert_input_only(), "tampered OE fails the readback");
    CHECK(fault_latched && strcmp(fault_code, "tap_dir") == 0, "latches tap_dir");
    supervise(); pump();
    CHECK(rp_ok_state == false && mock_gpio_out[PIN_RP_OK] == 0, "RP_OK refused while tampered");
    CHECK(tx_has("\"code\":\"tap_dir\"") && tx_has("\"m\":\"KICK\""), "fault names the tap");
    mock_gpio_dir[PIN_TAP_KICK] = GPIO_IN;      /* repair + recover */
    rx_feed("CLEAR\n"); poll_uart(); supervise();
    CHECK(tap_assert_input_only() && !fault_latched && rp_ok_state, "repair + CLEAR recovers");
    /* function-register tamper too */
    mock_gpio_funcsel[PIN_TAP_ARM] = GPIO_FUNC_UART;
    CHECK(!tap_assert_input_only(), "funcsel tamper also fails the readback");
    mock_gpio_funcsel[PIN_TAP_ARM] = GPIO_FUNC_SIO;
    rx_feed("CLEAR\n"); poll_uart(); supervise();

    /* ---- D: inverted decode (R3.1) — ONE inversion point ------------------ */
    printf("[D] inverted tap decode\n");
    reset_clean(); tap_init();
    mock_gpio_in[PIN_TAP_555] = 0;              /* raw LOW = FET on = observed HIGH */
    CHECK(tap_read(TAP_555) == true,  "raw 0 decodes as observed HIGH");
    mock_gpio_in[PIN_TAP_555] = 1;
    CHECK(tap_read(TAP_555) == false, "raw 1 decodes as observed LOW");
    mock_gpio_in[PIN_TAP_555] = 0; mock_gpio_in[PIN_TAP_ARM] = 0;
    CHECK(tap_mask() == 0x5u, "tap mask = bit0(555) | bit2(ARM) = 5");
    txr_head = txr_tail = 0; tx_reset();
    emit_hb(); pump();
    CHECK(tx_has("\"tap\":5"), "hb carries the post-inversion tap mask");
    CHECK(tx_has("\"rd\":0") && tx_has("\"ep\":1"), "hb carries ring depth + epoch");

    /* ---- E: edge ring capture + wraparound -------------------------------- */
    printf("[E] edge ring\n");
    reset_clean(); tap_init();
    mock_us = 10000000ull;                       /* t = 10000 ms */
    tap_edge_sim(PIN_TAP_KICK, 0);               /* raw fall -> observed RISE */
    advance_ms(7);
    tap_edge_sim(PIN_TAP_KICK, 1);               /* raw rise -> observed FALL */
    CHECK(tap_ring.count == 2, "two edges recorded");
    CHECK(tap_ring.ring[0].pin_idx == TAP_KICK && tap_ring.ring[0].level == 1
          && tap_ring.ring[0].t_ms == 10000u, "first entry: KICK rise @ 10000 ms");
    CHECK(tap_ring.ring[1].level == 0 && tap_ring.ring[1].t_ms == 10007u,
          "second entry: KICK fall @ +7 ms (1 ms timebase)");
    CHECK(tap_ring.ring[0].epoch == 1, "entries tagged with the current epoch");
    /* wraparound: overfill by 5; oldest must be evicted, depth saturates.
     * Spread the edges across storm-guard windows so the guard (correctly)
     * does not engage — the guard's own test is section [I]. */
    for (uint32_t i = 0; i < TAP_RING_SZ + 5u; i++) {
        advance_ms(3);
        tap_edge_sim(PIN_TAP_ARM, (int)(i & 1u));
    }
    CHECK(tap_ring.count == TAP_RING_SZ, "depth saturates at TAP_RING_SZ");
    CHECK(tap_ring.widx < TAP_RING_SZ, "write index stays in range after wrap");

    /* ---- F: reboot persistence + power-loss zeroing (R3.3) --------------- */
    printf("[F] noinit persistence semantics\n");
    reset_clean(); tap_init();
    tap_edge_sim(PIN_TAP_ARM, 0);
    tap_edge_sim(PIN_TAP_ARM, 1);
    CHECK(tap_ring.count == 2 && tap_ring.epoch == 1, "setup: 2 edges in epoch 1");
    tap_boot_init(true);                         /* simulate a WATCHDOG reboot */
    CHECK(tap_ring_preserved, "valid magic -> ring ADOPTED across reboot");
    CHECK(tap_ring.count == 2, "pre-reboot edges preserved");
    CHECK(tap_ring.epoch == 2, "epoch incremented");
    CHECK(tap_boot_reason == 2, "boot reason = watchdog");
    tap_edge_sim(PIN_TAP_ARM, 0);
    CHECK(tap_ring.ring[2].epoch == 2 && tap_ring.ring[0].epoch == 1,
          "post-reboot edges tagged epoch 2; old entries keep epoch 1");
    tap_ring.magic = 0xDEADBEEFu;                /* simulate true power loss */
    tap_boot_init(false);
    CHECK(!tap_ring_preserved && tap_ring.count == 0 && tap_ring.epoch == 1,
          "invalid magic -> zeroed ring, epoch restarts at 1");
    CHECK(tap_boot_reason == 0, "boot reason = cold power-up");
    /* torn-struct guard: good head magic but bad tail must NOT be adopted */
    tap_ring.magic = TAP_RING_MAGIC; tap_ring.magic2 = 0u; tap_ring.count = 7;
    tap_boot_init(false);
    CHECK(!tap_ring_preserved && tap_ring.count == 0, "bad tail magic -> zeroed (torn struct)");

    /* ---- G: TAPDUMP + cause classification -------------------------------- */
    printf("[G] TAPDUMP / cause codes\n");
    /* (a) kick starvation: live kick train AT THE REAL PI CADENCE (1 Hz: 50 ms
     * HIGH / 950 ms LOW per lane_node.py watchdog_kick_loop), then it stops,
     * then 555 falls. Silence must exceed TAP_KICK_STARVE_MS (2000 ms). */
    reset_clean(); tap_init();
    mock_us = 20000000ull;
    for (int i = 0; i < 3; i++) {                /* three 1 Hz kick pulses */
        tap_edge_sim(PIN_TAP_KICK, 0); advance_ms(50);   /* observed rise */
        tap_edge_sim(PIN_TAP_KICK, 1); advance_ms(950);  /* observed fall */
    }
    advance_ms(2500);                            /* kick silent > TAP_KICK_STARVE_MS */
    tap_edge_sim(PIN_TAP_555, 1);                /* raw rise = observed FALL of 555 */
    rx_feed("TAPDUMP\n"); poll_uart(); pump();
    CHECK(tx_has("\"ev\":\"tapdump\"") && tx_has("\"cause\":\"kick_starvation\""),
          "kick stops then 555 falls -> kick_starvation");
    tap_service(); pump();
    CHECK(tx_has("\"ev\":\"tape\"") && tx_has("\"ev\":\"tapdump_end\""),
          "dump entries + end marker delivered");
    CHECK(tx_has("\"p\":0") && tx_has("\"p\":1"), "entries carry tap indices (555 + KICK)");
    /* (a2) REGRESSION vs the v1.2.0 300 ms bug: a 555 fall landing in the normal
     * 1 Hz inter-kick gap (~950 ms after the last kick edge) is a live-train
     * 555/board fault -> "555_drop", NOT starvation. With the old 300 ms
     * threshold this exact case misclassified as kick_starvation. */
    reset_clean(); tap_init();
    mock_us = 25000000ull;
    tap_edge_sim(PIN_TAP_KICK, 0); advance_ms(50);
    tap_edge_sim(PIN_TAP_KICK, 1);               /* last kick edge */
    advance_ms(940);                             /* inside the normal 1 Hz gap */
    tap_edge_sim(PIN_TAP_555, 1);                /* observed 555 FALL, kick train live */
    tap_dump_start(); pump();
    CHECK(tx_has("\"cause\":\"555_drop\""),
          "555 falls mid normal 1 Hz kick gap -> 555_drop (not starvation)");
    /* (b) arm drop: ARM falls first, 555 follows inside the cluster */
    reset_clean(); tap_init();
    mock_us = 30000000ull;
    tap_edge_sim(PIN_TAP_KICK, 0);               /* recent kick — NOT starvation */
    advance_ms(50);
    tap_edge_sim(PIN_TAP_ARM, 1);                /* observed ARM fall */
    advance_ms(50);
    tap_edge_sim(PIN_TAP_555, 1);                /* observed 555 fall */
    tap_dump_start(); pump();
    CHECK(tx_has("\"cause\":\"arm_drop\""), "ARM falls first -> arm_drop");
    /* (c) self health: RPOK falls first */
    reset_clean(); tap_init();
    mock_us = 40000000ull;
    tap_edge_sim(PIN_TAP_RPOK, 1);
    advance_ms(30);
    tap_edge_sim(PIN_TAP_555, 1);
    tap_dump_start(); pump();
    CHECK(tx_has("\"cause\":\"self_health\""), "RPOK falls first -> self_health");
    /* (d) live kick at the 555 fall -> 555_drop, not starvation */
    reset_clean(); tap_init();
    mock_us = 50000000ull;
    tap_edge_sim(PIN_TAP_KICK, 0);
    advance_ms(100);
    tap_edge_sim(PIN_TAP_KICK, 1);
    advance_ms(100);                             /* kick edge 100 ms ago < TAP_KICK_STARVE_MS */
    tap_edge_sim(PIN_TAP_555, 1);
    tap_dump_start(); pump();
    CHECK(tx_has("\"cause\":\"555_drop\""), "555 falls with a live kick -> 555_drop");
    /* (e) empty ring */
    reset_clean(); tap_init();
    tap_dump_start(); pump();
    CHECK(tx_has("\"cause\":\"none\"") && tx_has("\"n\":0"), "empty ring -> cause none, n 0");

    /* ---- H: TAPCLR is the ONLY clear; ack; epoch survives ------------------ */
    printf("[H] TAPCLR\n");
    reset_clean(); tap_init();
    tap_edge_sim(PIN_TAP_ARM, 0); tap_edge_sim(PIN_TAP_ARM, 1);
    tap_boot_init(false);                        /* reboot does NOT clear ... */
    CHECK(tap_ring.count == 2 && tap_ring.epoch == 2, "reboot preserves; epoch now 2");
    rx_feed("TAPCLR\n"); poll_uart(); pump();
    CHECK(tap_ring.count == 0 && tap_ring.widx == 0, "TAPCLR empties the ring");
    CHECK(tap_ring.epoch == 2 && tap_ring.magic == TAP_RING_MAGIC, "TAPCLR keeps magic + epoch");
    CHECK(tx_has("\"ev\":\"ack\",\"cmd\":\"TAPCLR\""), "TAPCLR acked");

    /* ---- I: IRQ storm guard (floating-pin protection) ---------------------- */
    printf("[I] IRQ storm guard\n");
    reset_clean(); tap_init();
    mock_us = 60000000ull;
    for (uint32_t i = 0; i <= TAP_IRQ_BUDGET + 2u; i++)
        tap_edge_sim(PIN_TAP_555, (int)(i & 1u));     /* all inside one window */
    CHECK(mock_irq_mask[PIN_TAP_555] == 0, "over-budget tap's IRQ muted");
    CHECK((tap_irq_muted & 1u) != 0, "muted bit set for tap 0");
    CHECK(mock_irq_mask[PIN_TAP_KICK] != 0, "other taps unaffected");
    CHECK(!fault_latched, "storm guard is telemetry-only (no fault, no rail action)");
    advance_ms(TAP_IRQ_MUTE_MS + 10);
    tap_service();
    CHECK(mock_irq_mask[PIN_TAP_555] == (GPIO_IRQ_EDGE_FALL | GPIO_IRQ_EDGE_RISE),
          "IRQ re-enabled after cooldown");
    CHECK(tap_irq_muted == 0, "muted bit cleared");

    /* ---- J: ADC decode + hb min/max window (R3.4) -------------------------- */
    printf("[J] VCC_5V ADC\n");
    reset_clean(); tap_init();
    mock_adc_raw = 4095; adc_vcc5_sample();
    CHECK(adc_v5_mv == 6600, "full-scale raw -> 6600 mV (x2 divider)");
    mock_adc_raw = 2979; adc_vcc5_sample();      /* ~4.80 V */
    CHECK(adc_v5_mv >= 4795 && adc_v5_mv <= 4806, "mid-scale decodes to ~4.8 V");
    CHECK(adc_v5_min == adc_v5_mv && adc_v5_max == 6600, "window min/max track sag + peak");
    txr_head = txr_tail = 0; tx_reset();
    emit_hb(); pump();
    CHECK(tx_has("\"v5\":") && tx_has("\"v5n\":") && tx_has("\"v5x\":6600"),
          "hb carries v5 latest/min/max");
    adc_v5_window_reset();
    CHECK(adc_v5_min == adc_v5_mv && adc_v5_max == adc_v5_mv, "window reset collapses to latest");

    /* ---- K: RPOK cross-check — warn-only by default ------------------------ */
    printf("[K] GP19 vs GP2 cross-check\n");
    reset_clean(); tap_init();
    rp_ok_state = true; mock_gpio_in[PIN_TAP_RPOK] = 1;   /* tap says observed LOW */
    tap_hb_tick(); pump();
    CHECK(!tx_has("\"ev\":\"tapwarn\""), "single-tick mismatch: no warn yet (settle guard)");
    tap_hb_tick(); pump();
    CHECK(tx_has("\"ev\":\"tapwarn\",\"code\":\"rpok_mism\""), "persistent mismatch warns");
    CHECK(!fault_latched, "warn-only: no fault latched (enforcement compiled OFF)");
    mock_gpio_in[PIN_TAP_RPOK] = 0;              /* tap agrees again (observed HIGH) */
    tap_hb_tick();
    CHECK(rpok_mism_strikes == 0, "agreement resets the strike counter");

    /* ---- L: dump can never starve critical lines --------------------------- */
    printf("[L] dump starvation guard\n");
    reset_clean(); tap_init();
    for (int i = 0; i < 10; i++) { tap_edge_sim(PIN_TAP_ARM, i & 1); advance_ms(5); }
    mock_uart_writable = false;                  /* Pi not draining */
    rx_feed("TAPDUMP\n"); poll_uart();           /* header enqueued */
    /* stuff the ring until free space is below the dump's reserve */
    while (txr_free() >= (uint16_t)(TAPE_LINE_MAX + TXR_HEADROOM))
        emit("XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\n");
    { uint32_t p0 = dump_pos; tap_service();
      CHECK(dump_pos == p0, "no dump entries emitted while reserve is consumed"); }
    { uint32_t d0 = txr_drops; emit_hb();
      CHECK(txr_drops == d0, "hb still fits (dump left the headroom untouched)"); }
    mock_uart_writable = true; pump();           /* Pi drains */
    tap_service(); pump();
    CHECK(dump_pos == dump_n && tx_has("\"ev\":\"tapdump_end\""),
          "dump completes once space frees");

    /* ---- M: v1.2.2 R2-1 — pad-level OEOVER lock + mutation gate ------------ */
    /* Codex R2-1: the v1.2.0 invariant read the SIO direction only; CTRL.OEOVER
     * can force output-enable AT THE PAD with the SIO direction still reading
     * input. This section is the MUTATION GATE: simulate the override being
     * set and the invariant MUST trip (the test fails if it doesn't). */
    printf("[M] R2-1 pad-OE lock (OEOVER mutation gate)\n");
    reset_clean(); tap_init();
    {
        int locked = 1;
        for (uint i = 0; i < N_TAPS; i++) if (!pad_oe_locked(tap_pins[i])) locked = 0;
        CHECK(locked, "tap_init leaves GP16-19 OEOVER=DISABLE + OETOPAD=0");
        CHECK(pad_oe_locked(PIN_ADC_VCC5), "GP26 pad-OE locked after adc_gpio_init (post-CTRL-write order)");
        locked = 1;
        for (size_t i = 0; i < N_INPUTS; i++) if (!pad_oe_locked(inputs[i].gpio)) locked = 0;
        CHECK(locked, "fast inputs GP6-13 pad-OE locked by init_inputs (R2-1 scope)");
    }
    CHECK(tap_assert_input_only() && !fault_latched, "extended invariant passes on a clean init");
    /* mutation 1: OEOVER forced HIGH (output-enable at the pad, SIO dir untouched) */
    gpio_set_oeover(PIN_TAP_555, GPIO_OVERRIDE_HIGH);
    CHECK(mock_gpio_dir[PIN_TAP_555] == GPIO_IN, "setup: SIO direction STILL reads input (the C2-era blind spot)");
    CHECK(!tap_assert_input_only(), "OEOVER=HIGH mutation trips the readback (v1.2.1 missed this)");
    CHECK(fault_latched && strcmp(fault_code, "pad_oe") == 0, "latches pad_oe");
    supervise(); pump();
    CHECK(rp_ok_state == false, "RP_OK refused while the pad can drive");
    CHECK(tx_has("\"code\":\"pad_oe\"") && tx_has("\"m\":\"555\""), "fault names the tap");
    gpio_set_oeover(PIN_TAP_555, GPIO_OVERRIDE_LOW);         /* repair */
    rx_feed("CLEAR\n"); poll_uart(); supervise();
    CHECK(tap_assert_input_only() && !fault_latched && rp_ok_state, "repair + CLEAR recovers");
    /* mutation 2: OEOVER merely back to NORMAL (OETOPAD still 0 because dir is
     * input) — the DISABLE-field check must trip anyway: defense must not wait
     * for the pad to actually drive. */
    gpio_set_oeover(PIN_TAP_KICK, GPIO_OVERRIDE_NORMAL);
    CHECK((mock_iobank0.io[PIN_TAP_KICK].status & IO_BANK0_GPIO0_STATUS_OETOPAD_BITS) == 0,
          "setup: OETOPAD still 0 (pad not yet driving)");
    CHECK(!tap_assert_input_only() && strcmp(fault_code, "pad_oe") == 0,
          "OEOVER!=DISABLE trips even before the pad drives");
    gpio_set_oeover(PIN_TAP_KICK, GPIO_OVERRIDE_LOW);
    rx_feed("CLEAR\n"); poll_uart(); supervise();
    /* mutation 3: a rogue whole-CTRL rewrite (gpio_set_function) silently CLEARS
     * the override — real-SDK semantics the mock mirrors — and must be caught. */
    gpio_set_function(PIN_TAP_ARM, GPIO_FUNC_SIO);
    CHECK(!tap_assert_input_only() && strcmp(fault_code, "pad_oe") == 0,
          "whole-CTRL rewrite clears OEOVER -> invariant trips");
    gpio_set_oeover(PIN_TAP_ARM, GPIO_OVERRIDE_LOW);
    rx_feed("CLEAR\n"); poll_uart(); supervise();
    /* fast-input coverage: same mutation on a cam pin */
    gpio_set_oeover(PIN_SA, GPIO_OVERRIDE_HIGH);
    CHECK(!tap_assert_input_only(), "fast-input OEOVER mutation trips too");
    CHECK(strcmp(fault_code, "pad_oe") == 0, "fast-input mutation latches pad_oe");
    gpio_set_oeover(PIN_SA, GPIO_OVERRIDE_LOW);
    rx_feed("CLEAR\n"); poll_uart(); supervise();

    /* ---- N: v1.2.2 R2-13 — epoch-aware rail-drop classifier ---------------- */
    printf("[N] R2-13 epoch-aware classifier (stale-edge exclusion)\n");
    /* (a) pre-reboot edges alone must NOT classify after a reboot */
    reset_clean(); tap_init();
    mock_us = 70000000ull;
    tap_edge_sim(PIN_TAP_KICK, 0); advance_ms(50);
    tap_edge_sim(PIN_TAP_KICK, 1); advance_ms(2500);
    tap_edge_sim(PIN_TAP_555, 1);                 /* observed 555 FALL — epoch 1 */
    tap_dump_start(); pump();
    CHECK(tx_has("\"cause\":\"kick_starvation\""), "setup: classifies within epoch 1");
    tap_boot_init(true);                          /* watchdog reboot -> epoch 2, ring adopted */
    CHECK(tap_ring.count == 3 && tap_ring.epoch == 2, "setup: pre-reboot edges preserved into epoch 2");
    tx_reset(); txr_head = txr_tail = 0;
    tap_dump_start(); pump();
    CHECK(tx_has("\"cause\":\"none\""),
          "pre-reboot 555 fall is EXCLUDED from fresh diagnosis (v1.2.1 classified it)");
    tap_service(); pump();
    CHECK(tx_has("\"ep\":1"), "stale entries still dumped as history (per-entry epoch visible)");
    /* (b) stale edges must not STEER a fresh-epoch classification */
    reset_clean(); tap_init();
    mock_us = 80000000ull;
    tap_edge_sim(PIN_TAP_ARM, 1);                 /* epoch-1 ARM fall (would win as arm_drop) */
    advance_ms(20);
    tap_edge_sim(PIN_TAP_555, 1);                 /* epoch-1 555 fall */
    tap_boot_init(true);                          /* -> epoch 2 */
    advance_ms(3000);                             /* no epoch-2 kick edges at all */
    tap_edge_sim(PIN_TAP_555, 1);                 /* fresh epoch-2 555 fall */
    tx_reset(); txr_head = txr_tail = 0;
    tap_dump_start(); pump();
    CHECK(tx_has("\"cause\":\"kick_starvation\""),
          "fresh-epoch 555 fall classifies from epoch-2 evidence only (stale ARM fall ignored)");

    /* ---- O: v1.2.2 R2-6 — REV_ID strap read + floating detection ----------- */
    printf("[O] R2-6 REV_ID straps\n");
    reset_clean();
    /* rev-D strap pattern: GP20 -> 3V3 (1), GP21 -> GND (0) => code 0b01 */
    mock_gpio_floating[PIN_REV_ID0] = 0; mock_gpio_floating[PIN_REV_ID1] = 0;
    mock_gpio_in[PIN_REV_ID0] = 1; mock_gpio_in[PIN_REV_ID1] = 0;
    rev_id_init();
    CHECK(pcb_rev_code == REV_ID_REVD, "rev-D straps decode to 0b01");
    CHECK(strcmp(pcb_rev_name(), "revD") == 0, "code 0b01 names revD");
    CHECK(mock_gpio_pull[PIN_REV_ID0] == 0 && mock_gpio_pull[PIN_REV_ID1] == 0,
          "pulls disabled after the read (zero static strap current)");
    CHECK(pad_oe_locked(PIN_REV_ID0) && pad_oe_locked(PIN_REV_ID1),
          "REV_ID pins pad-OE locked after the read");
    CHECK(tap_assert_input_only(), "REV_ID pins joined the invariant contract set");
    gpio_set_oeover(PIN_REV_ID0, GPIO_OVERRIDE_HIGH);
    {
        bool tripped = !tap_assert_input_only();
        pump();
        CHECK(tripped && strcmp(fault_code, "pad_oe") == 0 && tx_has("\"m\":\"REV0\""),
              "REV_ID pad-OE mutation trips + names the pin");
    }
    gpio_set_oeover(PIN_REV_ID0, GPIO_OVERRIDE_LOW);
    rx_feed("CLEAR\n"); poll_uart(); supervise();
    /* floating pins (rev-B/rev-C board, no straps) follow the pull phases ->
     * disagree -> UNKNOWN, never assumed rev-D */
    mock_gpio_floating[PIN_REV_ID0] = 1; mock_gpio_floating[PIN_REV_ID1] = 1;
    rev_id_init();
    CHECK(pcb_rev_code == REV_ID_FLOATING, "floating straps detected via pull-phase disagreement");
    CHECK(strcmp(pcb_rev_name(), "unknown") == 0, "floating reports unknown (NOT rev-D)");
    mock_gpio_floating[PIN_REV_ID0] = 0; mock_gpio_floating[PIN_REV_ID1] = 0;

    /* ---- P: v1.2.2 R2-6 — identity line + hb rid --------------------------- */
    printf("[P] identity line\n");
    reset_clean();
    mock_gpio_in[PIN_REV_ID0] = 1; mock_gpio_in[PIN_REV_ID1] = 0;
    rev_id_init(); identity_init();
    txr_head = txr_tail = 0; tx_reset();
    emit_id(); pump();
    CHECK(tx_has("\"ev\":\"id\""), "id line emitted");
    CHECK(tx_has("\"fw\":\"phase8b-rp2040 v1.2.2\""), "id carries FW_VERSION v1.2.2");
    CHECK(tx_has("\"pcb\":\"revD\"") && tx_has("\"rid\":1"), "id carries the strap-read PCB rev");
    CHECK(tx_has("\"uid\":\"E66038B713952A31\""), "id carries the Pico unique id");
    CHECK(tx_has("\"build\":\"unknown\"") && tx_has("\"cfg\":\"unknown\""),
          "hostless build falls back to unknown build/cfg identity");
    CHECK(tx_has("\"fi1\":0"), "release build advertises fi1:0 (FA-11 banner identity)");
    txr_head = txr_tail = 0; tx_reset();
    emit_hb(); pump();
    CHECK(tx_has("\"rid\":1"), "hb carries the rid field every beat");
    /* ID command re-emits on demand */
    txr_head = txr_tail = 0; tx_reset();
    rx_feed("ID\n"); poll_uart(); pump();
    CHECK(tx_has("\"ev\":\"id\""), "ID command re-emits the identity line");

    /* ---- Q: v1.2.2 — FI-1 grammar does NOT exist in a release build --------- */
    printf("[Q] FI-1 compiled out of release\n");
    CHECK(FI1_ENABLED == 0, "FI1_ENABLED defaults OFF");
    reset_clean(); tap_init();
    memset(mock_dir_out_calls, 0, sizeof mock_dir_out_calls);
    memset(mock_put_calls, 0, sizeof mock_put_calls);
    txr_head = txr_tail = 0; tx_reset();
    rx_feed("FI1 ARM\n"); poll_uart();
    rx_feed("FI1 DRIVE 2\n"); poll_uart(); pump();
    CHECK(!tx_has("\"ev\":\"fi1\""), "FI1 commands produce NO response (unknown-line path)");
    {
        int tap_out = 0;
        for (uint i = 0; i < N_TAPS; i++)
            tap_out += mock_dir_out_calls[tap_pins[i]] + mock_put_calls[tap_pins[i]];
        CHECK(tap_out == 0, "FI1 DRIVE cannot touch a tap pin in a release image");
    }
    CHECK(!fault_latched, "ignored FI1 lines leave no fault behind");

    /* ---- R: round-3 fix 1 — main()'s LITERAL boot order must not latch ------ */
    /* Codex round-3 (2026-07-21 PM): v1.2.2 called tap_assert_input_only()
     * BEFORE init_inputs(); with GP6-13 at silicon reset state (FUNCSEL=NULL)
     * every boot latched a spurious "tap_dir"/SA fault and refused RP_OK. The
     * older tests never caught it because reset_clean() runs init_inputs()
     * before any assertion. This section replicates main()'s exact call order
     * on reset-state pins. */
    printf("[R] round-3 boot-order (invariant pass before init_inputs)\n");
    reset_clean();                                   /* housekeeping baseline */
    fault_latched = false; fault_code[0] = 0;
    inputs_inited = false; rev_id_inited = false;    /* statics as at real boot */
    for (int p = 0; p < 40; p++) {                   /* silicon reset: FUNCSEL=NULL, */
        mock_gpio_funcsel[p] = GPIO_FUNC_NULL;       /* input, OE disabled           */
        mock_gpio_dir[p] = GPIO_IN;
    }
    all_idle();
    mock_gpio_floating[PIN_REV_ID0] = 0; mock_gpio_floating[PIN_REV_ID1] = 0;
    mock_gpio_in[PIN_REV_ID0] = 1; mock_gpio_in[PIN_REV_ID1] = 0;
    /* --- main()'s literal order --- */
    gpio_init(PIN_RP_OK); gpio_set_dir(PIN_RP_OK, GPIO_OUT); gpio_put(PIN_RP_OK, 0);
    memset(&tap_ring, 0, sizeof tap_ring);           /* cold power-up */
    tap_boot_init(false);
    tap_init();
    rev_id_init(); identity_init();
    {
        bool pre_ok = tap_assert_input_only();       /* the line-1140 pass */
        CHECK(pre_ok && !fault_latched,
              "pre-init_inputs invariant pass is CLEAN (GP6-13 gated out of the set)");
    }
    init_inputs();
    CHECK(tap_assert_input_only() && !fault_latched,
          "post-init_inputs pass clean — inputs joined the contract set");
    mock_gpio_funcsel[PIN_DIELL_L] = GPIO_FUNC_UART; /* drift AFTER join must still trip */
    CHECK(!tap_assert_input_only() && strcmp(fault_code, "tap_dir") == 0,
          "input funcsel drift trips once the pin is in the set (gate is not a hole)");
    mock_gpio_funcsel[PIN_DIELL_L] = GPIO_FUNC_SIO;
    fault_latched = false; fault_code[0] = 0;

    /* ---- S: round-3 fix 2 — 16-bit epoch alias guard at ring adoption ------- */
    printf("[S] round-3 16-bit epoch alias guard\n");
    reset_clean(); tap_init();
    mock_us = 90000000ull;
    tap_edge_sim(PIN_TAP_KICK, 0); advance_ms(50);
    tap_edge_sim(PIN_TAP_KICK, 1); advance_ms(2500);
    tap_edge_sim(PIN_TAP_555, 1);                    /* observed 555 fall, tag (uint16)1 */
    CHECK(tap_ring.count == 3 && tap_ring.ring[2].epoch == 1, "setup: stale edges tagged epoch 1");
    tap_ring.epoch = 0x10000u;                       /* crash-loop fast-forward: next   */
    tap_boot_init(true);                             /* adoption -> 0x10001, low16 == 1 */
    CHECK(tap_ring.epoch == 0x10001u && tap_ring_preserved,
          "setup: adoption crossed the 64Ki horizon onto the stale tag value");
    CHECK(tap_ring.ring[0].epoch == 0 && tap_ring.ring[1].epoch == 0 && tap_ring.ring[2].epoch == 0,
          "colliding stale entries re-tagged to previous epoch at adoption (alias killed)");
    advance_ms(3000);
    tx_reset(); txr_head = txr_tail = 0;
    tap_dump_start(); pump();
    CHECK(tx_has("\"cause\":\"none\""),
          "aliased cross-boot 555 fall can no longer stamp a fresh cause code");
    tap_edge_sim(PIN_TAP_555, 1);                    /* a REAL fresh-epoch 555 fall */
    tx_reset(); txr_head = txr_tail = 0;
    tap_dump_start(); pump();
    CHECK(tx_has("\"cause\":\"kick_starvation\""),
          "fresh-epoch edges still classify after the guard re-tag");

    printf("\n%d/%d checks passed%s\n", checks - fails, checks, fails ? "  <<< FAILURES" : "");
    return fails ? 1 : 0;
}

/*
 * Host unit test for the RP2040 firmware logic (no hardware).
 * Mocks the Pico SDK, #includes main.c (with its main() renamed), and drives the
 * static functions to assert: TX ring buffer, debounce/edge detection, ball
 * lockout, UART command parsing, and the fail-safe RP_OK safety supervisor.
 *
 * Build + run (from firmware/rp2040/):
 *   clang -std=c11 -Wall -Wextra -I test -I test/stubs test/test_main.c -o test/test_main.exe
 *   ./test/test_main.exe          # exit 0 = all checks passed
 * (gcc works too; on Linux drop the .exe suffix.)
 */
#include "mock_pico.h"
#include "mock_impl.h"      /* shared mock state + bodies + harness helpers */
#include <stdio.h>
#include <string.h>

/* ---- pull in the firmware under test (rename its main) -------------------- */
#define main fw_main
#include "../main.c"
#undef main

/* pump() flushes the firmware's TX ring -> the capture buffer (needs txr_drain) */
static void pump(void) { txr_drain(); }

/* ---- assertions ---------------------------------------------------------- */
static int checks = 0, fails = 0;
#define CHECK(cond, msg) do { checks++; if (!(cond)) { fails++; printf("  FAIL: %s\n", msg); } \
                              else { printf("  ok:   %s\n", msg); } } while (0)

int main(void) {
    printf("== RP2040 firmware host logic test ==\n");

    /* ---- A: TX ring buffer --------------------------------------------- */
    printf("[A] TX ring\n");
    txr_head = txr_tail = 0; txr_drops = 0; tx_reset(); mock_uart_writable = true;
    emit("HELLO %d\n", 42); pump();
    CHECK(tx_has("HELLO 42"), "emit + drain delivers a line");
    txr_head = txr_tail = 0; txr_drops = 0; mock_uart_writable = false;
    for (int i = 0; i < 300; i++) emit("0123456789ABCDEF0123456789\n");  /* 27B * 300 >> 511 */
    CHECK(txr_drops > 0, "drops whole lines when ring full + not draining");
    mock_uart_writable = true; pump();

    /* ---- B: debounce + edge detection ---------------------------------- */
    printf("[B] debounce / edges\n");
    all_idle(); mock_us = 0; tap_init(); init_inputs(); tx_reset(); txr_head = txr_tail = 0;
    mock_gpio_in[PIN_SA] = 0;                      /* assert */
    scan_inputs(); pump();
    CHECK(!tx_has("\"id\":\"SA\""), "no edge before debounce window");
    advance_us(DEBOUNCE_CAM_US / 2); scan_inputs(); pump();
    CHECK(!tx_has("\"id\":\"SA\""), "no edge mid debounce window");
    advance_us(DEBOUNCE_CAM_US + 1); scan_inputs(); pump();
    CHECK(tx_has("\"ev\":\"cam\",\"id\":\"SA\",\"e\":\"f\""), "fall edge after debounce window");
    tx_reset();
    mock_gpio_in[PIN_SA] = 1; scan_inputs();       /* release */
    advance_us(DEBOUNCE_CAM_US + 1); scan_inputs(); pump();
    CHECK(tx_has("\"id\":\"SA\",\"e\":\"r\""), "rise edge after debounce window");
    /* glitch shorter than the window must NOT produce an edge */
    all_idle(); mock_us = 100000000ull; tap_init(); init_inputs(); tx_reset();
    mock_gpio_in[PIN_SB] = 0; scan_inputs();
    advance_us(DEBOUNCE_CAM_US / 2); scan_inputs();
    mock_gpio_in[PIN_SB] = 1; scan_inputs();        /* back to idle before stable */
    advance_us(DEBOUNCE_CAM_US * 2); scan_inputs(); pump();
    CHECK(!tx_has("\"id\":\"SB\""), "glitch shorter than window -> no edge");

    /* ---- C: ball detect + re-trigger lockout --------------------------- */
    printf("[C] ball lockout\n");
    all_idle(); mock_us = 200000000ull; tap_init(); init_inputs(); tx_reset(); last_ball_ms = 0;
    mock_gpio_in[PIN_DIELL_L] = 0; scan_inputs();
    advance_us(DEBOUNCE_DIELL_US + 1); scan_inputs(); pump();
    CHECK(tx_has("\"ev\":\"ball\",\"src\":\"L\""), "first beam-break emits a ball");
    tx_reset();
    mock_gpio_in[PIN_DIELL_L] = 1; scan_inputs(); advance_us(DEBOUNCE_DIELL_US + 1); scan_inputs();
    mock_gpio_in[PIN_DIELL_L] = 0; scan_inputs(); advance_us(DEBOUNCE_DIELL_US + 1); scan_inputs(); pump();
    CHECK(!tx_has("\"ev\":\"ball\""), "re-break within lockout is suppressed");
    tx_reset();
    mock_gpio_in[PIN_DIELL_L] = 1; scan_inputs(); advance_us(DEBOUNCE_DIELL_US + 1); scan_inputs();
    advance_ms(BALL_LOCKOUT_MS + 10);
    mock_gpio_in[PIN_DIELL_L] = 0; scan_inputs(); advance_us(DEBOUNCE_DIELL_US + 1); scan_inputs(); pump();
    CHECK(tx_has("\"ev\":\"ball\""), "re-break after lockout emits again");

    /* ---- D: UART command protocol -------------------------------------- */
    printf("[D] protocol\n");
    motors_all_stop();
    rx_feed("RUN S\n"); poll_uart();
    CHECK(find_motor("S")->running, "RUN S marks motor running");
    rx_feed("STOP S\n"); poll_uart();
    CHECK(!find_motor("S")->running, "STOP S clears it");
    rx_feed("RUN T\nRUN SP\n"); poll_uart();
    CHECK(find_motor("T")->running && find_motor("SP")->running, "two RUN lines");
    rx_feed("STOP *\n"); poll_uart();
    CHECK(!find_motor("T")->running && !find_motor("SP")->running, "STOP * clears all");
    tx_reset(); rx_feed("PING\n"); poll_uart(); pump();
    CHECK(tx_has("\"ev\":\"hb\""), "PING -> heartbeat");

    /* ---- E: RP_OK safety supervisor ------------------------------------ */
    printf("[E] RP_OK supervisor\n");
    all_idle(); tap_init(); init_inputs(); tx_reset();
    motors_all_stop(); fault_latched = false; fault_code[0] = 0;
    mock_us = 0; boot_ms = now_ms();
    rp_ok_state = true; mock_gpio_out[PIN_RP_OK] = 1;     /* force opposite to observe the drive */
    supervise();
    CHECK(rp_ok_state == false && mock_gpio_out[PIN_RP_OK] == 0, "RP_OK driven LOW before boot settle");
    advance_ms(BOOT_SETTLE_MS + 10); supervise();
    CHECK(rp_ok_state == true && mock_gpio_out[PIN_RP_OK] == 1, "RP_OK driven HIGH after settle, no fault");
    tx_reset();
    rx_feed("RUN S\n"); poll_uart();
    advance_ms(MAX_MOTION_MS + 5); supervise(); pump();
    CHECK(fault_latched, "guarded motor over max-run latches a fault");
    CHECK(rp_ok_state == false && mock_gpio_out[PIN_RP_OK] == 0, "RP_OK LOW on motion-timeout fault");
    CHECK(tx_has("\"code\":\"motion_timeout\""), "emits motion_timeout fault");
    CHECK(tx_has("\"m\":\"S\""), "names the offending motor");
    rx_feed("CLEAR\n"); poll_uart(); supervise();
    CHECK(!fault_latched, "CLEAR clears the latched fault");
    CHECK(rp_ok_state == true && mock_gpio_out[PIN_RP_OK] == 1, "RP_OK recovers HIGH after CLEAR");
    motors_all_stop(); fault_latched = false; fault_code[0] = 0;
    rx_feed("RUN BE\n"); poll_uart();
    advance_ms(MAX_MOTION_MS * 3); supervise();
    CHECK(!fault_latched, "BE (continuous) is NOT max-run-guarded");

    /* ---- F: UART fuzz / overrun discard / duplicate RUN ----------------- */
    printf("[F] UART fuzz / overrun discard\n");
    motors_all_stop(); fault_latched = false; fault_code[0] = 0;
    rx_discard = false; llen = 0;
    rx_feed("RUN S\n"); poll_uart();
    CHECK(find_motor("S")->running, "setup: RUN S running");
    {   /* duplicate RUN must NOT reset the max-run backstop timer */
        uint32_t t0 = find_motor("S")->t_start_ms;
        advance_ms(1000);
        rx_feed("RUN S\n"); poll_uart();
        CHECK(find_motor("S")->t_start_ms == t0, "duplicate RUN preserves t_start_ms (backstop not reset)");
    }
    {   /* oversized line whose tail would parse as a command pre-fix */
        char big[256]; int bl = 0;
        for (int i = 0; i < 100; i++) big[bl++] = 'X';        /* > 63 chars -> overrun */
        memcpy(&big[bl], "STOP S", 6); bl += 6;
        big[bl++] = '\n'; big[bl] = '\0';
        rx_feed(big); poll_uart();
        CHECK(find_motor("S")->running, "tail of an oversized line is NOT parsed (embedded STOP S swallowed)");
        rx_feed("STOP S\n"); poll_uart();
        CHECK(!find_motor("S")->running, "clean STOP S right after the garbage parses (newline resyncs)");
    }
    latch_fault("motion_timeout", "S");
    CHECK(fault_latched, "setup: fault latched");
    {   /* oversized line ending in CLEAR must not clear a latched fault */
        char big[256]; int bl = 0;
        for (int i = 0; i < 80; i++) big[bl++] = 'Y';
        memcpy(&big[bl], "CLEAR", 5); bl += 5;
        big[bl++] = '\n'; big[bl] = '\0';
        rx_feed(big); poll_uart();
        CHECK(fault_latched, "oversized line ending in CLEAR does NOT clear the fault");
        rx_feed("CLEAR\n"); poll_uart();
        CHECK(!fault_latched, "clean CLEAR after the garbage resyncs and clears");
    }
    motors_all_stop(); fault_latched = false; fault_code[0] = 0;
    rx_feed("RUN T\n"); poll_uart();
    {   /* 200-char garbage line with embedded command substrings */
        char big[256]; int bl = 0;
        for (int i = 0; i < 200; i++) big[bl++] = (char)('a' + (i % 26));
        memcpy(&big[40],  "STOP T", 6);
        memcpy(&big[120], "CLEAR",  5);
        big[bl++] = '\n'; big[bl] = '\0';
        rx_feed(big); poll_uart();
        CHECK(find_motor("T")->running, "200-char garbage line: motor state unchanged");
        CHECK(!fault_latched, "200-char garbage line: fault state unchanged");
    }
    {   /* 10k random bytes: no motor/fault change, no crash */
        unsigned seed = 12345u;
        for (int i = 0; i < 10000; i++) {
            seed = seed * 1103515245u + 12345u;
            mock_rx[mock_rx_head] = (char)((seed >> 16) & 0xFFu);
            mock_rx_head = (mock_rx_head + 1) % (int)sizeof(mock_rx);
            if ((i & 63) == 63) poll_uart();   /* drain so the mock ring never overflows */
        }
        poll_uart();
        CHECK(find_motor("T")->running && !find_motor("S")->running, "10k random bytes: motor states unchanged");
        CHECK(!fault_latched, "10k random bytes: no fault latched");
    }

    /* ---- G: uint32 ms wrap / boot-settle latch / CLEAR semantics --------- */
    printf("[G] ms wrap / boot latch / CLEAR\n");
    motors_all_stop(); fault_latched = false; fault_code[0] = 0;
    booted_done = false; rx_discard = false; llen = 0;
    mock_us = ((uint64_t)0xFFFFFFFFu * 1000u) - 500000u;   /* ~0.5 s of uint32 ms-count left */
    boot_ms = now_ms();
    supervise();
    CHECK(!rp_ok_state, "boot near wrap: RP_OK low before settle");
    advance_ms(BOOT_SETTLE_MS + 10); supervise();
    CHECK(rp_ok_state, "boot near wrap: RP_OK high after settle");
    advance_ms(2000); supervise();                         /* now_ms() itself wraps here */
    CHECK(rp_ok_state, "RP_OK stays HIGH across the uint32 ms wrap");
    /* the real failure mode: uptime crosses 2^32 ms (~49.7 days) and un-latched
     * settle math reads elapsed<BOOT_SETTLE_MS again for 200 ms */
    mock_us += (((uint64_t)1 << 32) - 2100u) * 1000u;      /* elapsed mod 2^32 = ~110ms */
    supervise();
    CHECK(rp_ok_state, "RP_OK held HIGH where un-latched math re-enters the settle window");
    latch_fault("motion_timeout", "S"); supervise();
    CHECK(!rp_ok_state, "a fault still drops RP_OK after the boot latch");
    rx_feed("CLEAR\n"); poll_uart(); supervise();
    CHECK(rp_ok_state, "CLEAR + supervise recovers RP_OK");
    /* CLEAR must also clear running marks so a stale RUN can't instantly re-latch */
    rx_feed("RUN S\n"); poll_uart();
    advance_ms(MAX_MOTION_MS + 5); supervise();
    CHECK(fault_latched, "setup: motion timeout re-latched");
    rx_feed("CLEAR\n"); poll_uart();
    CHECK(!find_motor("S")->running, "CLEAR clears running marks");
    supervise();
    CHECK(!fault_latched && rp_ok_state, "no instant re-latch after CLEAR");

    /* ---- H: chatter guard + TX ring headroom + oversized emit ------------ */
    printf("[H] chatter guard / ring headroom\n");
    all_idle(); mock_us += 1000000ull; tap_init(); init_inputs();
    motors_all_stop(); fault_latched = false; fault_code[0] = 0;
    rx_discard = false; llen = 0;
    txr_head = txr_tail = 0; txr_drops = 0; tx_reset(); mock_uart_writable = true;
    for (int i = 1; i <= 24 && !fault_latched; i++) {      /* ~1 debounced edge / 2ms */
        mock_gpio_in[PIN_SA] = (i & 1) ? 0 : 1;
        scan_inputs();
        advance_us(DEBOUNCE_CAM_US + 10);
        scan_inputs(); pump();
    }
    CHECK(fault_latched && strcmp(fault_code, "chatter") == 0, "sustained chatter latches a chatter fault");
    pump();
    CHECK(tx_has("\"code\":\"chatter\"") && tx_has("\"m\":\"SA\""), "chatter fault names the input");
    supervise();
    CHECK(!rp_ok_state, "chatter fault drops RP_OK (fail-safe)");
    rx_feed("CLEAR\n"); poll_uart(); tx_reset();
    for (int i = 1; i <= 6; i++) {                          /* sane mechanical rate */
        mock_gpio_in[PIN_TB] = (i & 1) ? 0 : 1;
        scan_inputs();
        advance_us(DEBOUNCE_CAM_US + 10); scan_inputs();
        advance_ms(200);
    }
    pump();
    CHECK(!fault_latched, "sane edge rate does not trip the chatter guard");
    CHECK(tx_has("\"id\":\"TB\""), "sane-rate edges still emitted");
    /* SLIDING-window (v1.1.1) DISCRIMINATION test. The old tumbling window reset
     * EDGE-ALIGNED (win_start = first edge after a >=100 ms gap), so a uniform burst
     * starting at the window origin lands in ONE aligned window and does NOT tell the
     * two algorithms apart (pre-flash review 2026-07-07, simulated both ways).
     * Discriminating shape: one ANCHOR edge (pins the old window origin at t0), a
     * 40 ms gap, then a 9-edge burst at ~12 ms spacing (edges ~t0+42 .. t0+138).
     * Old tumbling: [t0,t0+100) holds anchor+5 = 6 edges, next window holds 4 ->
     * NEVER latches. Sliding ring: the 9 burst edges span ~96 ms < 100 ms ->
     * latches exactly at the 9th burst edge. */
    {
        int lvl0 = mock_gpio_in[PIN_SB];
        mock_gpio_in[PIN_SB] = !lvl0;                      /* anchor edge */
        scan_inputs();
        advance_us(DEBOUNCE_CAM_US + 10); scan_inputs();   /* anchor lands at ~t0 */
        advance_ms(40);                                    /* gap: burst starts +40 ms */
        for (int i = 1; i <= 9 && !fault_latched; i++) {
            mock_gpio_in[PIN_SB] = (i & 1) ? lvl0 : !lvl0; /* 9 toggles = 9 edges */
            scan_inputs();
            advance_us(DEBOUNCE_CAM_US + 10); scan_inputs();  /* debounced edge lands */
            advance_ms(10);                                   /* ~12 ms total spacing */
        }
    }
    CHECK(fault_latched && strcmp(fault_code, "chatter") == 0,
          "anchored boundary-straddling burst latches (sliding window; old tumbling never latched this shape)");
    rx_feed("CLEAR\n"); poll_uart();
    CHECK(!fault_latched, "CLEAR recovers after the straddle test");
    /* ring headroom: an event flood cannot starve hb/flt */
    txr_head = txr_tail = 0; txr_drops = 0; tx_reset(); mock_uart_writable = false;
    for (int i = 0; i < 50; i++) emit_evt("{\"ev\":\"cam\",\"id\":\"SA\",\"e\":\"f\",\"t\":1}\n");
    CHECK(txr_drops > 0, "evt lines stop enqueueing at the headroom limit");
    {
        uint32_t d0 = txr_drops;
        emit_hb();
        CHECK(txr_drops == d0, "hb still fits in the reserved headroom");
    }
    mock_uart_writable = true; pump();
    CHECK(tx_has("\"ev\":\"hb\""), "hb delivered despite the evt flood");
    /* an emit longer than fmtbuf is dropped whole — no torn bytes in the ring */
    txr_head = txr_tail = 0; txr_drops = 0; tx_reset();
    {
        char longline[300];
        memset(longline, 'q', sizeof(longline) - 1); longline[sizeof(longline) - 1] = '\0';
        emit("%s\n", longline);
        CHECK(txr_drops == 1 && txr_head == txr_tail, "oversized emit dropped whole (never truncated)");
    }

    /* ---- I: hb input/run masks ------------------------------------------ */
    printf("[I] hb input/run masks\n");
    all_idle(); mock_us += 1000000ull; tap_init(); init_inputs();
    motors_all_stop(); fault_latched = false; fault_code[0] = 0;
    rx_discard = false; llen = 0;
    mock_gpio_in[PIN_SC] = 0;                               /* assert SC (bit 2) */
    scan_inputs(); advance_us(DEBOUNCE_CAM_US + 1); scan_inputs();
    rx_feed("RUN T\n"); poll_uart();                        /* T (bit 1) */
    txr_head = txr_tail = 0; tx_reset(); mock_uart_writable = true;
    emit_hb(); pump();
    CHECK(tx_has("\"in\":4"), "hb carries the input level mask (SC = bit 2)");
    CHECK(tx_has("\"run\":2"), "hb carries the running-motor mask (T = bit 1)");

    /* ---- J: v1.1 supervision DISABLED-by-default is inert (no new enforcement) ----------- */
    /* The cam-stop overrun / SC-TB echo / motion-without-RUN checks all default OFF (config.h
     * flags 0, trips UNCONFIRMED). This pins that a DEFAULT build behaves EXACTLY like v0.2.0:
     * NONE of them ever latches a fault. The ENABLED behavior is proven in test_v11.c, built
     * with the flags -D'd on. */
    printf("[J] v1.1 supervision off-by-default is inert\n");
    CHECK(FW_VERSION[0] != 0 && strstr(FW_VERSION, "v1.2") != NULL, "FW_VERSION bumped to v1.2");
    CHECK(CAM_SA_STOP_ENABLED == 0 && CAM_TA1_STOP_ENABLED == 0
          && INTERLOCK_ECHO_ENABLED == 0 && MOTION_NO_RUN_ENABLED == 0,
          "all v1.1 enforcement flags default OFF");
    CHECK(CAM_SA_TRIP == CAM_TRIP_UNCONFIRMED && CAM_TA1_TRIP == CAM_TRIP_UNCONFIRMED,
          "cam trip edges default UNCONFIRMED");
    {   /* boot "v11" posture: a default/stock build must advertise everything OFF */
        char sa_p[4], ta1_p[4];
        camstop_posture_str(sa_p,  (bool)CAM_SA_STOP_ENABLED,  CAM_SA_TRIP);
        camstop_posture_str(ta1_p, (bool)CAM_TA1_STOP_ENABLED, CAM_TA1_TRIP);
        CHECK(strcmp(sa_p, "off") == 0 && strcmp(ta1_p, "off") == 0,
              "default build advertises sa/ta1 = \"off\" in the boot v11 posture");
    }
    all_idle(); mock_us += 1000000ull; tap_init(); init_inputs(); init_camstops();
    motors_all_stop(); fault_latched = false; fault_code[0] = 0;
    rx_discard = false; llen = 0;
    /* (a) cam-stop overrun: RUN S, trip SA, never STOP, wait well past any grace -> NO fault */
    rx_feed("RUN S\n"); poll_uart();
    mock_gpio_in[PIN_SA] = 0; scan_inputs(); advance_us(DEBOUNCE_CAM_US + 1); scan_inputs();
    advance_ms(2000); supervise();
    CHECK(!fault_latched, "default: cam trip + un-STOPped motor does NOT latch (overrun off)");
    /* (b) motion-without-RUN: stop all, trip SA with nothing running -> NO fault */
    rx_feed("STOP *\n"); poll_uart(); fault_latched = false; fault_code[0] = 0;
    mock_gpio_in[PIN_SA] = 1; scan_inputs(); advance_us(DEBOUNCE_CAM_US + 1); scan_inputs();
    mock_gpio_in[PIN_SA] = 0; scan_inputs(); advance_us(DEBOUNCE_CAM_US + 1); scan_inputs();
    supervise();
    CHECK(!fault_latched, "default: cam trip with no motor running does NOT latch (no-run off)");
    /* (c) SC/TB echo: assert SC AND TB with a motor running -> NO fault (echo off) */
    fault_latched = false; fault_code[0] = 0;
    rx_feed("RUN T\n"); poll_uart();
    mock_gpio_in[PIN_SC] = 0; mock_gpio_in[PIN_TB] = 0;
    scan_inputs(); advance_us(DEBOUNCE_CAM_US + 1); scan_inputs();
    supervise();
    CHECK(!fault_latched, "default: SC AND TB both asserted does NOT latch (echo off)");
    rx_feed("STOP *\n"); poll_uart();

    printf("\n%d/%d checks passed%s\n", checks - fails, checks, fails ? "  <<< FAILURES" : "");
    return fails ? 1 : 0;
}

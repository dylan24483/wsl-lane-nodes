/*
 * Host unit test for the v1.1 SAFETY supervision paths with the enforcement flags ENABLED.
 *
 * The default test (test_main.c) proves the v1.1 checks are inert when their config flags are
 * OFF (the shipped default). This binary compiles the SAME firmware (../main.c) with the flags
 * forced ON and confirmed trip edges, then proves each new fault path actually fires fail-safe:
 *   (1) cam-stop OVERRUN      — stop-cam trip, motor not STOPped in grace -> "cam_overrun" + RP_OK low
 *   (2) SC/TB interlock echo  — SC AND TB both asserted while a motor runs -> "interlock_collision"
 *   (3) motion-without-RUN    — stop-cam trip with no motion motor running -> "motion_no_run"
 * plus the disarm/cleanup semantics (a timely STOP, or CLEAR, prevents/recovers the latch).
 *
 * Build + run (from firmware/rp2040/):
 *   gcc -std=c11 -Wall -Wextra -I test -I test/stubs \
 *       -DCAM_SA_STOP_ENABLED=1 -DCAM_SA_TRIP="'f'" -DCAM_SA_GRACE_MS=150u \
 *       -DCAM_TA1_STOP_ENABLED=1 -DCAM_TA1_TRIP="'f'" -DCAM_TA1_GRACE_MS=150u \
 *       -DINTERLOCK_ECHO_ENABLED=1 -DMOTION_NO_RUN_ENABLED=1 \
 *       test/test_v11.c -o test/test_v11.exe
 *   ./test/test_v11.exe          # exit 0 = all checks passed
 *
 * NOTE: these -D values are TEST polarities ('f' = the active-low default assumption). They do
 * NOT confirm the real cam polarity — that is the §3.2 bench field capture. This binary only
 * proves the LOGIC is correct once a polarity is chosen.
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

/* drive one full debounced cam edge: set raw level, settle past the debounce window */
static void cam_edge(uint pin, int level) {
    mock_gpio_in[pin] = level;
    scan_inputs();
    advance_us(DEBOUNCE_CAM_US + 1);
    scan_inputs();
}

static int checks = 0, fails = 0;
#define CHECK(cond, msg) do { checks++; if (!(cond)) { fails++; printf("  FAIL: %s\n", msg); } \
                              else { printf("  ok:   %s\n", msg); } } while (0)

/* reset firmware + mock state to a clean armed-and-healthy baseline */
static void reset_clean(void) {
    all_idle(); mock_us += 5000000ull;
    tap_init();                 /* v1.2.3: real boot configures taps/ADC input-only
                                 * BEFORE init_inputs() — the CLEAR pad-revalidation
                                 * (R3-6) reads them back, so the harness must too */
    init_inputs(); init_camstops();
    motors_all_stop();
    fault_latched = false; fault_code[0] = 0;
    rx_discard = false; llen = 0;
    mock_rx_head = mock_rx_tail = 0;
    txr_head = txr_tail = 0; txr_drops = 0; tx_reset(); mock_uart_writable = true;
    booted_done = true;                       /* past boot-settle for these tests */
    rp_ok_state = true; mock_gpio_out[PIN_RP_OK] = 1;
}

int main(void) {
    printf("== RP2040 firmware v1.1 supervision test (flags ENABLED) ==\n");

    /* sanity: the flags really are on in this TU */
    printf("[pre] flags on\n");
    CHECK(CAM_SA_STOP_ENABLED == 1 && CAM_TA1_STOP_ENABLED == 1
          && INTERLOCK_ECHO_ENABLED == 1 && MOTION_NO_RUN_ENABLED == 1,
          "v1.1 enforcement flags forced ON in this build");
    CHECK(CAM_SA_TRIP == 'f' && CAM_TA1_TRIP == 'f', "test trip edges = 'f'");
    {   /* boot "v11" posture: an armed build must advertise its trip edge (finding 37) */
        char p[4];
        camstop_posture_str(p, (bool)CAM_SA_STOP_ENABLED, CAM_SA_TRIP);
        CHECK(strcmp(p, "f") == 0, "armed build advertises sa=\"f\" in the boot v11 posture");
    }

    /* ---- 1: cam-stop OVERRUN -------------------------------------------- */
    printf("[1] cam-stop overrun\n");
    reset_clean();
    rx_feed("RUN S\n"); poll_uart();
    CHECK(find_motor("S")->running, "setup: S running");
    cam_edge(PIN_SA, 0);                       /* SA trip (fall) while S runs -> arm grace */
    CHECK(camstops[0].armed, "SA trip while S runs arms the grace timer");
    advance_ms(CAM_SA_GRACE_MS / 2); supervise();
    CHECK(!fault_latched, "mid-grace, no STOP yet: no fault");
    advance_ms(CAM_SA_GRACE_MS); supervise(); pump();
    CHECK(fault_latched && strcmp(fault_code, "cam_overrun") == 0,
          "grace elapses with motor still running -> cam_overrun latched");
    CHECK(rp_ok_state == false && mock_gpio_out[PIN_RP_OK] == 0, "RP_OK driven LOW on cam_overrun");
    CHECK(tx_has("\"code\":\"cam_overrun\"") && tx_has("\"m\":\"SA\""), "fault names the cam (SA)");
    rx_feed("CLEAR\n"); poll_uart(); supervise();
    CHECK(!fault_latched && rp_ok_state, "CLEAR recovers RP_OK");
    CHECK(!camstops[0].armed, "CLEAR disarms the grace window");

    /* a TIMELY STOP within grace must PREVENT the latch */
    printf("[1b] timely STOP cancels the overrun\n");
    reset_clean();
    rx_feed("RUN S\n"); poll_uart();
    cam_edge(PIN_SA, 0);
    CHECK(camstops[0].armed, "setup: armed by SA trip");
    advance_ms(CAM_SA_GRACE_MS / 2);
    rx_feed("STOP S\n"); poll_uart();          /* Pi obeys the cam edge in time */
    CHECK(!camstops[0].armed, "STOP S within grace disarms the window");
    advance_ms(CAM_SA_GRACE_MS * 2); supervise();
    CHECK(!fault_latched, "no cam_overrun when STOP arrived within grace");

    /* a trip while the motor is NOT running does not arm (it's a normal stopped cam pass) */
    printf("[1c] trip with motor stopped does not arm overrun\n");
    reset_clean();
    /* motion-without-RUN is also on, so to isolate the overrun-arm path we keep T running
     * (a different motor) so any_motion_running() is true and no-run can't fire on SA. */
    rx_feed("RUN T\n"); poll_uart();
    cam_edge(PIN_SA, 0);                        /* SA trip, but S (its motor) is NOT running */
    CHECK(!camstops[0].armed, "SA trip with S stopped does not arm the SA overrun window");
    advance_ms(CAM_SA_GRACE_MS * 2); supervise();
    CHECK(!fault_latched, "no overrun fault when the cam's own motor was already stopped");

    /* a RE-TRIP inside the window must NOT refresh the deadline (finding 56: contact
     * bounce below the chatter threshold could otherwise extend the grace forever) */
    printf("[1e] re-trip does not extend the grace window\n");
    reset_clean();
    rx_feed("RUN S\n"); poll_uart();
    cam_edge(PIN_SA, 0);                        /* first trip fixes the deadline */
    CHECK(camstops[0].armed, "setup: armed by the first SA trip");
    {
        uint32_t armed0 = camstops[0].armed_ms;
        advance_ms(CAM_SA_GRACE_MS / 2);
        cam_edge(PIN_SA, 1);                    /* bounce: release ... */
        cam_edge(PIN_SA, 0);                    /* ... and re-trip inside the window */
        CHECK(camstops[0].armed && camstops[0].armed_ms == armed0,
              "re-trip inside the window does not move armed_ms");
    }
    advance_ms(CAM_SA_GRACE_MS); supervise();   /* > grace since the FIRST trip */
    CHECK(fault_latched && strcmp(fault_code, "cam_overrun") == 0,
          "overrun latches on the FIRST trip's deadline despite the re-trip");

    /* TA1 -> table (T) path, independent of the SA descriptor */
    printf("[1d] TA1/table overrun is independent\n");
    reset_clean();
    rx_feed("RUN T\n"); poll_uart();
    cam_edge(PIN_TA1, 0);
    CHECK(camstops[1].armed, "TA1 trip while T runs arms the table grace timer");
    advance_ms(CAM_TA1_GRACE_MS + 50); supervise(); pump();
    CHECK(fault_latched && strcmp(fault_code, "cam_overrun") == 0 && tx_has("\"m\":\"TA1\""),
          "TA1 overrun latches cam_overrun naming TA1");

    /* ---- 2: SC/TB interlock echo --------------------------------------- */
    printf("[2] SC/TB collision echo\n");
    reset_clean();
    rx_feed("RUN T\n"); poll_uart();           /* a motion motor is running */
    cam_edge(PIN_SC, 0);                        /* SC asserted */
    supervise();
    CHECK(!fault_latched, "SC alone (TB idle) does not latch");
    cam_edge(PIN_TB, 0);                        /* now TB asserted too */
    supervise(); pump();
    CHECK(fault_latched && strcmp(fault_code, "interlock_collision") == 0,
          "SC AND TB both asserted while a motor runs -> interlock_collision");
    CHECK(rp_ok_state == false, "RP_OK LOW on interlock_collision");

    /* SC AND TB asserted but NO motion motor running -> no collision course (nothing moving) */
    printf("[2b] SC+TB with nothing running does not latch\n");
    reset_clean();
    cam_edge(PIN_SC, 0); cam_edge(PIN_TB, 0);
    supervise();
    CHECK(!fault_latched, "SC+TB asserted but no motor running -> no interlock fault");

    /* ---- 3: motion-without-RUN ----------------------------------------- */
    printf("[3] motion-without-RUN\n");
    reset_clean();
    /* nothing running; a stop-cam trip means the machine is turning uncommanded */
    cam_edge(PIN_SA, 0); supervise(); pump();   /* supervise() drives RP_OK each loop pass */
    CHECK(fault_latched && strcmp(fault_code, "motion_no_run") == 0,
          "SA trip with no motor running -> motion_no_run latched");
    CHECK(rp_ok_state == false, "RP_OK LOW on motion_no_run");
    CHECK(tx_has("\"code\":\"motion_no_run\"") && tx_has("\"m\":\"SA\""), "fault names the cam");

    /* a trip WHILE a motion motor runs is commanded motion, not uncommanded -> NOT motion_no_run
     * (it routes to the overrun-arm path instead) */
    printf("[3b] trip while commanded is not motion_no_run\n");
    reset_clean();
    rx_feed("RUN T\n"); poll_uart();
    cam_edge(PIN_TA1, 0);                       /* T is running -> this is a guarded stop, not no-run */
    CHECK(!(fault_latched && strcmp(fault_code, "motion_no_run") == 0),
          "trip with a motion motor running does not raise motion_no_run");
    CHECK(camstops[1].armed, "it arms the overrun window instead");

    /* the non-trip edge ('r' release) must do nothing for any v1.1 check */
    printf("[3c] non-trip (release) edge is inert\n");
    reset_clean();
    cam_edge(PIN_SA, 0);                        /* assert (would arm/no-run) ... */
    fault_latched = false; fault_code[0] = 0;   /* ignore that; we test the release next */
    camstop_all_disarm();
    cam_edge(PIN_SA, 1);                        /* release: 'r' is NOT the configured trip */
    CHECK(!fault_latched, "release edge raises no v1.1 fault");
    CHECK(!camstops[0].armed, "release edge arms nothing");

    printf("\n%d/%d checks passed%s\n", checks - fails, checks, fails ? "  <<< FAILURES" : "");
    return fails ? 1 : 0;
}

/*
 * Host unit test for the v1.2.2 FI-1 bench fault-injection build (Codex R2-13 /
 * remediation spec R1.9). This binary compiles the SAME main.c with
 * -DFI1_ENABLED=1 — the bench-only image that drives GP16-19 output-high on
 * command for the FA-7 unidirectionality proof. It pins the three gates:
 *   (1) physical BOOTSEL jumper: absent -> PERMANENT fi1_nojumper refusal
 *       (re-latched past CLEAR; every FI1 command answered "refused");
 *   (2) arm command: "FI1 DRIVE" before "FI1 ARM" is ignored;
 *   (3) release/restore: "FI1 RELEASE" returns every driven pin to the locked
 *       input-only contract and the extended invariant passes again.
 * Plus: a driven pin is EXEMPT from the invariant while driving (deliberate,
 * bench-only), non-driven pins stay enforced, and the id line carries "fi1":1
 * (FA-11 step 3 banner identity).
 *
 * Build + run (from firmware/rp2040/):
 *   gcc -std=c11 -Wall -Wextra -Werror -I test -I test/stubs -DFI1_ENABLED=1 \
 *       test/test_fi1.c -o test/test_fi1.exe
 *   ./test/test_fi1.exe          # exit 0 = all checks passed
 */
#include "mock_pico.h"
#include "mock_impl.h"      /* shared mock state + bodies + harness helpers */
#include <stdio.h>
#include <string.h>

/* ---- pull in the firmware under test (rename its main) -------------------- */
#define main fw_main
#include "../main.c"
#undef main

/* The FI-1 build's physical-jumper check (fi1_bootsel.c on the target) — the
 * host test owns the mock. */
static int mock_fi1_jumper = 0;
bool fi1_jumper_present(void) { return mock_fi1_jumper != 0; }

static void pump(void) { txr_drain(); }

static int checks = 0, fails = 0;
#define CHECK(cond, msg) do { checks++; if (!(cond)) { fails++; printf("  FAIL: %s\n", msg); } \
                              else { printf("  ok:   %s\n", msg); } } while (0)

static void reset_clean(void) {
    all_idle(); mock_us += 5000000ull;
    memset(&tap_ring, 0, sizeof tap_ring);
    tap_boot_init(false);
    init_inputs(); init_camstops();
    motors_all_stop();
    fault_latched = false; fault_code[0] = 0;
    rx_discard = false; llen = 0;
    mock_rx_head = mock_rx_tail = 0;
    txr_head = txr_tail = 0; txr_drops = 0; tx_reset(); mock_uart_writable = true;
    booted_done = true;
    rp_ok_state = true; mock_gpio_out[PIN_RP_OK] = 1;
    fi1_refused = false; fi1_armed = false; fi1_driving = 0;
}

int main(void) {
    (void)advance_us; (void)advance_ms;   /* shared harness helpers unused here */
    printf("== RP2040 firmware v1.2.2 FI-1 bench-build test (R2-13 / R1.9) ==\n");

    printf("[pre] posture\n");
    CHECK(FI1_ENABLED == 1, "this binary IS the FI-1 build");
    CHECK(strstr(FW_VERSION, "v1.2.2") != NULL, "FW_VERSION v1.2.2");

    /* ---- A: no jumper -> permanent refusal -------------------------------- */
    printf("[A] physical-jumper gate\n");
    reset_clean(); tap_init();
    mock_fi1_jumper = 0;
    fi1_init();
    CHECK(fi1_refused, "no jumper -> refused");
    CHECK(fault_latched && strcmp(fault_code, "fi1_nojumper") == 0, "latches fi1_nojumper");
    supervise(); pump();
    CHECK(rp_ok_state == false, "RP_OK refused");
    rx_feed("CLEAR\n"); poll_uart();
    CHECK(!fault_latched, "setup: CLEAR momentarily clears the latch");
    supervise();
    CHECK(fault_latched && strcmp(fault_code, "fi1_nojumper") == 0,
          "supervise RE-LATCHES past CLEAR (refusal is permanent this power cycle)");
    txr_head = txr_tail = 0; tx_reset();
    rx_feed("FI1 ARM\n"); poll_uart(); pump();
    CHECK(tx_has("\"op\":\"refused\""), "FI1 ARM answered refused");
    memset(mock_dir_out_calls, 0, sizeof mock_dir_out_calls);
    rx_feed("FI1 DRIVE 2\n"); poll_uart();
    {
        int tap_out = 0;
        for (uint i = 0; i < N_TAPS; i++) tap_out += mock_dir_out_calls[tap_pins[i]];
        CHECK(tap_out == 0 && fi1_driving == 0, "refused build cannot drive a tap");
    }

    /* ---- B: jumper present -> arm gate + drive + invariant exemption ------- */
    printf("[B] arm + drive\n");
    reset_clean(); tap_init();
    mock_fi1_jumper = 1;
    fi1_init();
    CHECK(!fi1_refused && !fault_latched, "jumper present -> runs normally");
    memset(mock_dir_out_calls, 0, sizeof mock_dir_out_calls);
    memset(mock_put_calls, 0, sizeof mock_put_calls);
    rx_feed("FI1 DRIVE 2\n"); poll_uart();          /* DRIVE before ARM */
    CHECK(fi1_driving == 0 && mock_dir_out_calls[PIN_TAP_ARM] == 0,
          "DRIVE before ARM is ignored");
    txr_head = txr_tail = 0; tx_reset();
    rx_feed("FI1 ARM\n"); poll_uart(); pump();
    CHECK(fi1_armed && tx_has("\"op\":\"armed\""), "FI1 ARM arms + acks");
    rx_feed("FI1 DRIVE 2\n"); poll_uart(); pump();  /* tap idx 2 = ARM tap = GP18 */
    CHECK(tx_has("\"op\":\"drive\",\"p\":2"), "DRIVE acked with the tap index");
    CHECK(mock_gpio_dir[PIN_TAP_ARM] == 1 && mock_gpio_out[PIN_TAP_ARM] == 1,
          "pin driven OUTPUT-HIGH (FA-7 step 2)");
    CHECK(mock_gpio_oeover[PIN_TAP_ARM] == GPIO_OVERRIDE_NORMAL,
          "pad OE unlocked for the drive (deliberate)");
    CHECK(mock_irq_mask[PIN_TAP_ARM] == 0, "driven pin's tap IRQ muted (no self-edge storm)");
    CHECK((fi1_driving & (1u << TAP_ARM)) != 0, "driving mask tracks it");
    /* invariant: driven pin exempt, everything else still enforced */
    CHECK(tap_assert_input_only() && !fault_latched,
          "invariant passes with the driven pin exempted");
    gpio_set_oeover(PIN_TAP_555, GPIO_OVERRIDE_HIGH);      /* a NON-driven tap drifts */
    CHECK(!tap_assert_input_only() && strcmp(fault_code, "pad_oe") == 0,
          "non-driven taps stay enforced while one is driven");
    gpio_set_oeover(PIN_TAP_555, GPIO_OVERRIDE_LOW);
    rx_feed("CLEAR\n"); poll_uart(); supervise();
    CHECK(!fault_latched, "recovered");

    /* ---- C: release restores the locked contract --------------------------- */
    printf("[C] release\n");
    txr_head = txr_tail = 0; tx_reset();
    rx_feed("FI1 RELEASE\n"); poll_uart(); pump();
    CHECK(tx_has("\"op\":\"released\",\"ok\":1"), "RELEASE acks with a PASSING re-verify");
    CHECK(fi1_driving == 0 && !fi1_armed, "driving mask cleared + disarmed");
    CHECK(mock_gpio_dir[PIN_TAP_ARM] == GPIO_IN, "pin back to input");
    CHECK(pad_oe_locked(PIN_TAP_ARM), "pad OE re-locked (OEOVER=DISABLE)");
    CHECK(mock_irq_mask[PIN_TAP_ARM] == (GPIO_IRQ_EDGE_FALL | GPIO_IRQ_EDGE_RISE),
          "tap IRQ re-enabled");
    CHECK(tap_assert_input_only() && !fault_latched, "full invariant green after release");
    rx_feed("FI1 DRIVE 1\n"); poll_uart();
    CHECK(fi1_driving == 0, "RELEASE disarmed: a new DRIVE needs a new ARM");

    /* ---- D: banner identity ------------------------------------------------ */
    printf("[D] banner identity\n");
    txr_head = txr_tail = 0; tx_reset();
    emit_id(); pump();
    CHECK(tx_has("\"fi1\":1"), "id line advertises fi1:1 (FA-11 step 3)");

    printf("\n%d/%d checks passed%s\n", checks - fails, checks, fails ? "  <<< FAILURES" : "");
    return fails ? 1 : 0;
}

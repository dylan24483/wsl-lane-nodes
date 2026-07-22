/*
 * WSL Phase 8b — RP2040 lane-controller co-processor — firmware v0.1.0
 * =====================================================================
 * One RP2040 (Pico module) per lane on the rev-B controller board. It is the
 * FAST + SAFETY half of the controller; the Raspberry Pi runs the cycle FSM
 * (lane_node/cycle_control_8270.py) over an MCP23017/relay path. This firmware:
 *
 *   1. Reads the 8 fast inputs (6 cams + 2 DIELL ball beams), de-bounces them,
 *      and PUSHES edge events to the Pi over uart0 (the FSM consumes events, it
 *      does not poll — removes Pi-scheduling latency from cam timing).
 *   2. Drives RP2040_OK (GP2) = the rail-permission line in the relay-enable-rail
 *      AND chain. HIGH only when healthy; LOW on boot, fault, or hang. This is a
 *      first-class, non-bypassable safety-rail condition (spec §4.1/§4.2).
 *   3. Provides the RP2040's UART-INDEPENDENT safety contributions:
 *        - firmware health (RP2040 hardware watchdog: a hung loop resets the chip
 *          -> GP2 goes Hi-Z -> external 100k pulldown -> rail drops);
 *        - motion max-run backstop ("cam timeout"): if the Pi marks a guarded
 *          motor RUNNING (RUN <m>) and never STOPs it within MAX_MOTION_MS, the
 *          firmware latches a fault and drops RP_OK.
 *   4. Heartbeats to the Pi so a dead/!ok RP2040 is detected (Pi then drops ARM).
 *
 * SAFETY MODEL (read before editing — sources: docs/phase8b_pcb_revB_spec.md §4,
 * docs/phase8_8270_SYSTEM_REFERENCE.md §5):
 *   - This board is NEVER the only safety device for the Stop/CIS/master-breaker
 *     chain, the NE555 watchdog (watches the *Pi*), or regenerative motor
 *     braking — those are in hardware, independent of this firmware. The TB/SC
 *     collision interlock is the EXCEPTION: it is PLANNED hardware only — design
 *     open per docs/phase8_interlock_redesign.md (measured 2026-06-27: the
 *     J_SAFETY NC loop is unbuildable as drawn). Until it lands, the software
 *     echo is the ONLY TB/SC guard.
 *   - RP_OK is FAIL-SAFE LOW. Telemetry must NEVER block the safety loop: UART TX
 *     is a non-blocking ring buffer; the RP_OK drive + watchdog kick run every
 *     loop pass regardless of UART state. A dead UART cannot cause unsafe motion
 *     (no RUN msgs -> nothing marked running; and the Pi's own motion-timeout
 *     FAULT drops ARM).
 *
 * DEFERRED to v1.1 (NOT in this firmware, on purpose):
 *   - Cam-stop OVERRUN enforcement (stop-cam fires while a motor is RUNNING and
 *     the Pi fails to STOP within a grace window -> drop RP_OK). It needs the
 *     per-cam edge->angle polarity that is a deferred cutover field item
 *     (phase8_trackB_controller_cutover_runbook.md §3.2). Do NOT bake in unconfirmed
 *     cam polarity. The hook is marked  // v1.1  below.
 *   - SC/TB collision echo gating RP_OK (the hardware J_SAFETY loop is PLANNED
 *     only — design open per docs/phase8_interlock_redesign.md; the firmware
 *     echo is enabled once the SC/TB windows are bench-confirmed).
 *
 * This firmware is bench-bring-up gated (spec §12.9) before any live machine.
 */
#include <stdio.h>
#include <string.h>
#include <stdarg.h>

#include "pico/stdlib.h"
#include "hardware/uart.h"
#include "hardware/gpio.h"
#include "hardware/watchdog.h"
#include "hardware/adc.h"       /* v1.2: VCC_5V sense on GP26/ADC0            */
#include "hardware/sync.h"      /* v1.2: IRQ-safe tap-ring snapshot/clear     */
#include "hardware/structs/io_bank0.h"  /* v1.2.2: CTRL.OEOVER + STATUS.OETOPAD readback (R2-1) */
#include "pico/unique_id.h"     /* v1.2.2: Pico unique board id (identity line, R2-6) */

#ifdef WSL_EMBED_BUILD_ID
#include "build_id.h"           /* generated per build: WSL_BUILD_GIT / WSL_CFG_SHA */
#endif

#include "config.h"

#define UART_ID uart0

/* compile-time printf-format checking on the event logger (emit) */
#if defined(__GNUC__) || defined(__clang__)
#define EMIT_FMT __attribute__((format(printf, 1, 2)))
#else
#define EMIT_FMT
#endif

/* ====================================================================== */
/*  Time helpers                                                          */
/* ====================================================================== */
static inline uint32_t now_ms(void) { return to_ms_since_boot(get_absolute_time()); }

/* ====================================================================== */
/*  Non-blocking UART TX ring  (telemetry must never stall the safety loop)*/
/* ====================================================================== */
#define TXR_SZ 1024   /* v1.2: 512 -> 1024 (hb line grew; TXR_HEADROOM grew in lockstep) */
static uint8_t  txr[TXR_SZ];
static uint16_t txr_head = 0, txr_tail = 0;
static uint32_t txr_drops = 0;     /* whole lines dropped because the ring was full */

static uint16_t txr_free(void) { return (uint16_t)((txr_tail - txr_head - 1u + TXR_SZ) % TXR_SZ); }

/* Enqueue a whole line or none (never a partial line -> Pi parser never sees a torn JSON). */
static void txr_push(const char *s, int n) {
    if (n <= 0) return;
    if (txr_free() < (uint16_t)n) { txr_drops++; return; }
    for (int i = 0; i < n; i++) { txr[txr_head] = (uint8_t)s[i]; txr_head = (uint16_t)((txr_head + 1u) % TXR_SZ); }
}

/* Drain as many bytes as the UART FIFO will take this pass; never blocks. */
static void txr_drain(void) {
    while (txr_head != txr_tail && uart_is_writable(UART_ID)) {
        uart_putc_raw(UART_ID, (char)txr[txr_tail]);
        txr_tail = (uint16_t)((txr_tail + 1u) % TXR_SZ);
    }
}

/* Format an event line (caller includes the trailing '\n') and enqueue it.
 * A line that does not fit fmtbuf is dropped WHOLE (counted in txr_drops) —
 * never truncated, because a torn line without its '\n' would glue onto the
 * next line at the Pi parser and corrupt BOTH.
 *   emit()     — critical lines (boot/hb/flt/rp_ok/ack): may fill the ring.
 *   emit_evt() — cam/ball telemetry: only enqueued while TXR_HEADROOM bytes
 *                stay free, so an event flood can never starve hb/flt/rp_ok. */
/* SIZE BUDGET (re-counted for v1.2.2, 2026-07-21): the longest single lines are
 *   boot = ~147 B v1.1.1 worst + 36 B tap{} block            = ~183 B worst
 *   hb   = ~110 B v1.1.1 worst + ~64 B tap/rd/ep/v5* + 10 B rid = ~184 B worst
 *   id   = ~85 B fixed + fw 21 + pcb 7 + rid 3 + uid 16 + build<=32 + cfg<=16
 *          + t 10 (build/cfg/uid are %.Ns-capped)             = ~190 B worst
 * fmtbuf 256 (~65 B margin). If you ADD A FIELD, re-count the worst case or the
 * whole line silently drops (visible only as txr_drops) and the Pi loses it.
 * Grow fmtbuf with the line, never trust it silently. TXR_HEADROOM (320) must
 * stay >= the worst flt+rp_ok+hb burst (~60+40+184 = 284) — re-check it too. */
static char fmtbuf[256];
static void emit_v(bool lowprio, const char *fmt, va_list ap) {
    int n = vsnprintf(fmtbuf, sizeof(fmtbuf), fmt, ap);
    if (n <= 0) return;
    if (n >= (int)sizeof(fmtbuf)) { txr_drops++; return; }      /* drop whole, never tear */
    if (lowprio && txr_free() < (uint16_t)(n + TXR_HEADROOM)) { txr_drops++; return; }
    txr_push(fmtbuf, n);
#if DEBUG_USB
    fwrite(fmtbuf, 1, (size_t)n, stdout);
#endif
}
static void emit(const char *fmt, ...) EMIT_FMT;
static void emit(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt); emit_v(false, fmt, ap); va_end(ap);
}
static void emit_evt(const char *fmt, ...) EMIT_FMT;
static void emit_evt(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt); emit_v(true, fmt, ap); va_end(ap);
}

/* ====================================================================== */
/*  v1.2.2 pad-level output-enable lock (Codex R2-1)                       */
/* ====================================================================== */
/* The v1.2.0/v1.2.1 input-only invariant read back the SIO OE + IO-bank
 * function registers ONLY. The RP2040's per-pin CTRL.OEOVER field bypasses
 * both: OEOVER=ENABLE/HIGH forces the pad's output-enable ON at the pad
 * regardless of the SIO direction, so a rogue write to one IO_BANK0 CTRL
 * register could drive an "input-only" pin while the old readback stayed
 * green. Fix (R2-1):
 *   - force_pad_input_only() is the ONE lock point: CTRL.OEOVER = DISABLE.
 *     Called LAST in each pin-config choke point (gpio_init/gpio_set_function
 *     rewrite the whole CTRL register and would silently clear the override —
 *     ordering is load-bearing; the host mock mirrors that clearing).
 *   - pad_oe_locked() verifies BOTH the CTRL.OEOVER field still reads
 *     DISABLE AND the live pad STATUS.OETOPAD bit reads 0 (the actual
 *     output-enable reaching the pad). Checked at init and every heartbeat
 *     tick by tap_assert_input_only() for EVERY input-contract pin (taps
 *     GP16-19, ADC GP26, fast inputs GP6-13, REV_ID GP20-21); drift latches
 *     a fail-safe "pad_oe" fault -> RP_OK drops.                            */
static void force_pad_input_only(uint p) { gpio_set_oeover(p, GPIO_OVERRIDE_LOW); }

static bool pad_oe_locked(uint p) {
    uint32_t ctrl = io_bank0_hw->io[p].ctrl;
    if (((ctrl & IO_BANK0_GPIO0_CTRL_OEOVER_BITS) >> IO_BANK0_GPIO0_CTRL_OEOVER_LSB)
        != IO_BANK0_GPIO0_CTRL_OEOVER_VALUE_DISABLE)
        return false;
    return (io_bank0_hw->io[p].status & IO_BANK0_GPIO0_STATUS_OETOPAD_BITS) == 0u;
}

/* ====================================================================== */
/*  Fast inputs: time-based debounce + edge detection                     */
/* ====================================================================== */
/* Ring capacity for the SLIDING chatter window: must cover the largest per-
 * input budget. 8 inputs x 32 x 4 B = 1 KB static — trivial on the RP2040. */
#define CHATTER_RING_MAX 32u
#if CHATTER_MAX_CAM > CHATTER_RING_MAX || CHATTER_MAX_DIELL > CHATTER_RING_MAX
#error "CHATTER_RING_MAX must cover the largest CHATTER_MAX_* budget"
#endif

typedef struct {
    const char *id;
    uint        gpio;
    uint32_t    debounce_us;
    bool        is_ball;        /* DIELL beams -> coalesced into one "ball" event */
    uint8_t     chatter_max;    /* max debounced edges per CHATTER_WINDOW_MS before fault */
    /* runtime */
    bool        stable_asserted;
    bool        cand_asserted;
    uint64_t    cand_since_us;
    /* sliding chatter window: timestamps of the last chatter_max debounced edges */
    uint32_t    edge_ring[CHATTER_RING_MAX];
    uint8_t     ring_n;         /* edges recorded so far (saturates at chatter_max) */
    uint8_t     ring_i;         /* next write slot = the OLDEST recorded edge once full */
} input_t;

static input_t inputs[] = {
    { "SA",      PIN_SA,      DEBOUNCE_CAM_US,   false, CHATTER_MAX_CAM,   false, false, 0, {0}, 0, 0 },
    { "SB",      PIN_SB,      DEBOUNCE_CAM_US,   false, CHATTER_MAX_CAM,   false, false, 0, {0}, 0, 0 },
    { "SC",      PIN_SC,      DEBOUNCE_CAM_US,   false, CHATTER_MAX_CAM,   false, false, 0, {0}, 0, 0 },
    { "TA1",     PIN_TA1,     DEBOUNCE_CAM_US,   false, CHATTER_MAX_CAM,   false, false, 0, {0}, 0, 0 },
    { "TA2",     PIN_TA2,     DEBOUNCE_CAM_US,   false, CHATTER_MAX_CAM,   false, false, 0, {0}, 0, 0 },
    { "TB",      PIN_TB,      DEBOUNCE_CAM_US,   false, CHATTER_MAX_CAM,   false, false, 0, {0}, 0, 0 },
    { "DIELL_L", PIN_DIELL_L, DEBOUNCE_DIELL_US, true,  CHATTER_MAX_DIELL, false, false, 0, {0}, 0, 0 },
    { "DIELL_R", PIN_DIELL_R, DEBOUNCE_DIELL_US, true,  CHATTER_MAX_DIELL, false, false, 0, {0}, 0, 0 },
};
#define N_INPUTS (sizeof(inputs) / sizeof(inputs[0]))

static uint32_t last_ball_ms = 0;

static void latch_fault(const char *code, const char *motor);   /* defined below */
static void camstop_on_cam_edge(const char *cam_id, char edge); /* v1.1, defined below */

/* Round-3 boot-order fix (Codex 2026-07-21 PM, finding 1): the fast inputs
 * GP6-13 join the tap_assert_input_only() contract set only AFTER init_inputs()
 * has configured them. main() runs the first invariant pass BEFORE init_inputs()
 * (taps/ADC must be enforced from the first moment), and at that point GP6-13
 * are still at silicon reset state (FUNCSEL=NULL, not SIO) — an ungated check
 * latched a spurious "tap_dir"/SA fault on EVERY boot of the v1.2.2 image and
 * refused RP_OK until an operator PBZ. Same pattern as rev_id_inited. */
static bool inputs_inited = false;

static void init_inputs(void) {
    uint64_t t = time_us_64();
    for (size_t i = 0; i < N_INPUTS; i++) {
        input_t *in = &inputs[i];
        gpio_init(in->gpio);
        gpio_set_dir(in->gpio, GPIO_IN);
        gpio_pull_up(in->gpio);                 /* belt + suspenders with the on-board 10k */
        force_pad_input_only(in->gpio);         /* v1.2.2 R2-1: OEOVER=DISABLE, LAST (see lock section) */
        bool asserted = (gpio_get(in->gpio) == 0);   /* active-low */
        in->stable_asserted = asserted;
        in->cand_asserted   = asserted;
        in->cand_since_us   = t;
        in->ring_n          = 0;
        in->ring_i          = 0;
    }
    inputs_inited = true;       /* pins now in the invariant contract set */
}

/* Debounced asserted level of an input by id (false if the id is unknown). Used by the v1.1
 * SC/TB interlock echo in supervise() — level-based, robust vs a single dropped cam edge. */
static bool input_asserted(const char *id) {
    for (size_t i = 0; i < N_INPUTS; i++)
        if (strcmp(inputs[i].id, id) == 0) return inputs[i].stable_asserted;
    return false;
}

static void scan_inputs(void) {
    uint64_t t = time_us_64();
    for (size_t i = 0; i < N_INPUTS; i++) {
        input_t *in = &inputs[i];
        bool asserted = (gpio_get(in->gpio) == 0);
        if (asserted != in->cand_asserted) {        /* raw changed -> restart the stability timer */
            in->cand_asserted = asserted;
            in->cand_since_us = t;
        }
        if (asserted != in->stable_asserted &&
            (t - in->cand_since_us) >= in->debounce_us) {
            in->stable_asserted = asserted;         /* debounced edge */

            /* Chatter guard: a failing contact that passes debounce at a
             * sustained rate is an electrical fault. Latch (fail-safe: drops
             * RP_OK via supervise) and suppress the event flood so hb/flt
             * lines keep flowing on the UART. State tracking above still runs
             * so the hb "in" mask stays truthful.
             *
             * SLIDING window (v1.1.1): the ring holds the last chatter_max
             * debounced edge times; if the edge chatter_max-edges-ago is still
             * inside CHATTER_WINDOW_MS, THIS edge is edge chatter_max+1 within
             * one window -> fault. (The old tumbling window reset its count at
             * each boundary, so a burst straddling it needed up to 2x the
             * budget to latch.) The edge is recorded even when latching, so
             * the flood suppression tracks the true rate for as long as the
             * input actually chatters. */
            uint32_t em = now_ms();
            bool burst = (in->ring_n >= in->chatter_max &&
                          (uint32_t)(em - in->edge_ring[in->ring_i]) < CHATTER_WINDOW_MS);
            in->edge_ring[in->ring_i] = em;
            if (++in->ring_i >= in->chatter_max) in->ring_i = 0;
            if (in->ring_n < in->chatter_max) in->ring_n++;
            if (burst) {
                latch_fault("chatter", in->id);
                continue;
            }

            if (in->is_ball) {
                if (asserted) {                     /* beam broken = ball passing */
                    uint32_t m = now_ms();
                    if ((uint32_t)(m - last_ball_ms) >= BALL_LOCKOUT_MS) {
                        last_ball_ms = m;
                        emit_evt("{\"ev\":\"ball\",\"src\":\"%c\",\"t\":%lu}\n",
                                 in->id[6], (unsigned long)m);   /* id[6] = 'L' or 'R' */
                    }
                }
            } else {
                /* Forward the cam edge; direction f=asserted(fall), r=released(rise).
                 * Which edge is the angular "trip" is bench-confirmed per cam — the
                 * Pi/daemon maps cam+state -> FSM method (see firmware README). */
                char e = asserted ? 'f' : 'r';
                emit_evt("{\"ev\":\"cam\",\"id\":\"%s\",\"e\":\"%c\",\"t\":%lu}\n",
                         in->id, e, (unsigned long)now_ms());
                /* v1.1: arm the cam-stop grace timer / motion-without-RUN check for this
                 * edge (no-op on a default/unconfirmed build). Runs even if the cam event
                 * line was dropped for telemetry headroom — safety must not depend on TX. */
                camstop_on_cam_edge(in->id, e);
            }
        }
    }
}

/* ====================================================================== */
/*  Motor run-tracking (fed by the Pi over UART) for the max-run backstop  */
/* ====================================================================== */
typedef struct {
    const char *name;
    bool        guarded;     /* subject to the max-run timeout? */
    bool        running;
    uint32_t    t_start_ms;
} motor_t;

static motor_t motors[] = {
    { "S",  true,  false, 0 },
    { "T",  true,  false, 0 },
    { "SP", true,  false, 0 },
    { "M2", true,  false, 0 },
    { "M1", true,  false, 0 },
    { "BE", false, false, 0 },   /* continuous back-end motor — not timed */
    { "M",  false, false, 0 },   /* master/power — not a motion motor      */
};
#define N_MOTORS (sizeof(motors) / sizeof(motors[0]))

static motor_t *find_motor(const char *name) {
    for (size_t i = 0; i < N_MOTORS; i++)
        if (strcmp(motors[i].name, name) == 0) return &motors[i];
    return NULL;
}

static void motors_all_stop(void) {
    for (size_t i = 0; i < N_MOTORS; i++) motors[i].running = false;
}

/* Any GUARDED (motion) motor currently marked running? Used by the v1.1 SC/TB echo and
 * motion-without-RUN checks: BE (continuous back-end) and M (master/power) are not motion
 * and never count as "the machine is moving under command". */
static bool any_motion_running(void) {
    for (size_t i = 0; i < N_MOTORS; i++)
        if (motors[i].guarded && motors[i].running) return true;
    return false;
}

/* ====================================================================== */
/*  v1.1 cam-stop overrun: per-stop-cam descriptors + armed grace timers   */
/* ====================================================================== */
/* A stop cam, its trip edge, the motor it stops, and the grace window the Pi has to send
 * STOP after the trip. enabled + trip default to OFF/UNCONFIRMED (config.h) so a board with
 * no §3.2 polarity capture behaves EXACTLY like v0.2.0 (no enforcement). 'motor' is resolved
 * once at init. The armed/armed_ms runtime fields hold an in-flight grace window. */
typedef struct {
    const char *cam;          /* input id this descriptor watches                 */
    char        trip_edge;    /* 'f'/'r' = the angular zero-stop trip; '?' = never */
    const char *motor_name;
    uint32_t    grace_ms;
    bool        enabled;
    /* runtime */
    motor_t    *motor;        /* resolved from motor_name at init                 */
    bool        armed;        /* a trip happened, waiting out the grace window     */
    uint32_t    armed_ms;
} camstop_t;

static camstop_t camstops[] = {
    { "SA",  CAM_SA_TRIP,  "S", CAM_SA_GRACE_MS,  (bool)CAM_SA_STOP_ENABLED,  NULL, false, 0 },
    { "TA1", CAM_TA1_TRIP, "T", CAM_TA1_GRACE_MS, (bool)CAM_TA1_STOP_ENABLED, NULL, false, 0 },
};
#define N_CAMSTOPS (sizeof(camstops) / sizeof(camstops[0]))

static void init_camstops(void) {
    for (size_t i = 0; i < N_CAMSTOPS; i++) {
        camstops[i].motor = find_motor(camstops[i].motor_name);
        camstops[i].armed = false;
        camstops[i].armed_ms = 0;
    }
}

/* A cam input fired a DEBOUNCED edge ('f' asserted / 'r' released). Evaluate the two
 * EDGE-DRIVEN v1.1 checks for it (the grace-timeout half runs in supervise()). All paths are
 * gated on the per-descriptor enable + a CONFIRMED (non-'?') trip edge, so a default/unconfirmed
 * build does nothing here. Only ever arms a timer or latch_fault()s — never permits motion. */
static void camstop_on_cam_edge(const char *cam_id, char edge) {
    for (size_t i = 0; i < N_CAMSTOPS; i++) {
        camstop_t *cs = &camstops[i];
        if (strcmp(cs->cam, cam_id) != 0) continue;
        if (cs->trip_edge == CAM_TRIP_UNCONFIRMED) continue;   /* never trips while unconfirmed */
        bool is_trip = (edge == cs->trip_edge);
        if (!is_trip) continue;

        /* (3) motion-without-RUN: a stop-cam trip with NO motion motor running at all means the
         * machine is turning uncommanded (Pi wedged / external start / welded relay). */
        if (MOTION_NO_RUN_ENABLED && !any_motion_running()) {
            latch_fault("motion_no_run", cs->cam);
            return;
        }

        /* (1) cam-stop overrun: trip while THIS cam's guarded motor is running -> the Pi must
         * STOP it within grace_ms or supervise() latches. Armed on the FIRST trip only: a
         * contact bouncing below the chatter threshold must NOT keep refreshing the window
         * (each refresh would extend the Pi's STOP deadline toward the 8 s max-run). The
         * window disarms only via STOP <m> / STOP * / CLEAR (camstop_motor_stopped/all_disarm). */
        if (cs->enabled && cs->motor && cs->motor->running && !cs->armed) {
            cs->armed = true;
            cs->armed_ms = now_ms();
        }
    }
}

/* A STOP for `mt` disarms any cam-stop grace window guarding it (the Pi obeyed in time). */
static void camstop_motor_stopped(const motor_t *mt) {
    for (size_t i = 0; i < N_CAMSTOPS; i++)
        if (camstops[i].motor == mt) camstops[i].armed = false;
}

static void camstop_all_disarm(void) {
    for (size_t i = 0; i < N_CAMSTOPS; i++) camstops[i].armed = false;
}

/* ====================================================================== */
/*  Safety supervisor: drive RP_OK (fail-safe low)                        */
/* ====================================================================== */
static bool     fault_latched = false;
static char     fault_code[20] = "";
static bool     rp_ok_state    = false;   /* mirrors the GP2 level */
static uint32_t boot_ms        = 0;
static bool     booted_done    = false;   /* latched once, BOOT_SETTLE_MS after boot */

#if FI1_ENABLED
/* FI-1 bench build state (v1.2.2, R2-13/R1.9 — compiled OUT of release; see config.h).
 * Declared here (ahead of supervise + the tap invariant) so the refusal re-latch and
 * the driven-pin invariant exemption can see them; the command handlers live after the
 * tap section. */
static bool    fi1_refused = false;   /* booted WITHOUT the physical BOOTSEL jumper      */
static bool    fi1_armed   = false;   /* "FI1 ARM" received (required before any DRIVE)  */
static uint8_t fi1_driving = 0;       /* bitmask of taps currently driven output-high    */
#endif

static void set_rp_ok(bool ok) {
    if (ok != rp_ok_state) {
        rp_ok_state = ok;
        gpio_put(PIN_RP_OK, ok ? 1 : 0);
        emit("{\"ev\":\"rp_ok\",\"v\":%d,\"t\":%lu}\n", ok ? 1 : 0, (unsigned long)now_ms());
    }
}

static void latch_fault(const char *code, const char *motor) {
    if (fault_latched) return;
    fault_latched = true;
    strncpy(fault_code, code, sizeof(fault_code) - 1);
    fault_code[sizeof(fault_code) - 1] = '\0';
    emit("{\"ev\":\"flt\",\"code\":\"%s\",\"m\":\"%s\",\"t\":%lu}\n",
         code, motor ? motor : "", (unsigned long)now_ms());
}

static void supervise(void) {
    uint32_t m = now_ms();

#if FI1_ENABLED
    /* FI-1 jumper refusal is PERMANENT for the whole power cycle: a CLEAR must
     * not resurrect a fault-injection build that booted without its physical
     * jumper (R1.9 "must refuse to run"). Re-latch on every pass. */
    if (fi1_refused && !fault_latched) latch_fault("fi1_nojumper", "");
#endif

    /* Max-run backstop: a guarded motor RUNNING longer than MAX_MOTION_MS -> fault. */
    if (!fault_latched) {
        for (size_t i = 0; i < N_MOTORS; i++) {
            if (motors[i].guarded && motors[i].running &&
                (uint32_t)(m - motors[i].t_start_ms) > MAX_MOTION_MS) {
                latch_fault("motion_timeout", motors[i].name);
                break;
            }
        }
    }

    /* v1.1 (1) cam-stop OVERRUN: an armed grace window whose guarded motor is STILL running
     * past grace_ms -> the Pi failed to stop on the cam edge -> latch (Pi-independent stop).
     * A motor that already stopped disarmed the window in handle_line(); guard on running too
     * in case of any race. No-op unless a descriptor is enabled with a confirmed trip edge. */
    if (!fault_latched) {
        for (size_t i = 0; i < N_CAMSTOPS; i++) {
            camstop_t *cs = &camstops[i];
            if (!cs->armed) continue;
            if (!cs->enabled || !cs->motor || !cs->motor->running) { cs->armed = false; continue; }
            if ((uint32_t)(m - cs->armed_ms) > cs->grace_ms) {
                latch_fault("cam_overrun", cs->cam);
                break;
            }
        }
    }

    /* v1.1 (2) SC/TB collision-interlock echo: both interlock cams asserted at once while a
     * motion motor runs = the sweep+table collision course the hardware J_SAFETY loop guards.
     * Echo it in firmware (backstop of a backstop). Uses DEBOUNCED levels (robust vs a single
     * dropped edge, and matches the hb "in" mask the Pi resyncs from). No-op unless enabled. */
    if (INTERLOCK_ECHO_ENABLED && !fault_latched) {
        if (input_asserted("SC") && input_asserted("TB") && any_motion_running())
            latch_fault("interlock_collision", "SCTB");
    }

    /* Boot settle is LATCHED: the un-latched comparison re-enters the settle
     * window every 2^32 ms (~49.7 days of uptime) and would un-assert RP_OK
     * for 200 ms, hard-stopping the lane. Faults still drop RP_OK instantly —
     * the latch only ever widens the "booted" term, never the fault term. */
    if (!booted_done && (uint32_t)(m - boot_ms) >= BOOT_SETTLE_MS) booted_done = true;
    set_rp_ok(booted_done && !fault_latched);
}

/* ====================================================================== */
/*  v1.2 rev-D diagnostic taps (GP16-19) + VCC_5V ADC (GP26) — spec R3    */
/* ====================================================================== */
/* Read config.h's v1.2 block first. Summary of the contract:
 *   - GP16-19 are INPUT-ONLY as an ENFORCED invariant: tap_init() is the single
 *     choke-point that configures them; tap_assert_input_only() reads back the
 *     SIO OE + IO-bank function registers each heartbeat tick and latch_fault()s
 *     (fail-safe: RP_OK drops) on drift. NOTHING else may touch these pins —
 *     the host test (test/test_v12.c) fails on any output-direction/write call.
 *   - All four taps are INVERTED by the 2N7002 stage; tap_read() is the ONE
 *     inversion point. Everything on the wire is observed-net truth.
 *   - Both-edge IRQs feed a 1 ms-timestamped ring in noinit RAM that survives
 *     reboot (magic pair + epoch). Cleared only by TAPCLR, never by boot.
 *   - Telemetry only: nothing here permits motion, feeds the watchdog, or
 *     bypasses a fault. Every failure direction is latch_fault or lost telemetry. */

static const uint  tap_pins[]  = { PIN_TAP_555, PIN_TAP_KICK, PIN_TAP_ARM, PIN_TAP_RPOK };
static const char *tap_names[] = { "555", "KICK", "ARM", "RPOK" };
#define N_TAPS 4u
enum { TAP_555 = 0, TAP_KICK = 1, TAP_ARM = 2, TAP_RPOK = 3 };
#define TAP_IRQ_EDGES (GPIO_IRQ_EDGE_FALL | GPIO_IRQ_EDGE_RISE)

/* THE single inversion point (R3.1): raw pad LOW = FET on = observed net HIGH. */
static inline bool tap_read(uint idx) { return gpio_get(tap_pins[idx]) == 0; }

/* Observed-net levels as a bitmask for the hb line (bit order = tap index). */
static unsigned tap_mask(void) {
    unsigned v = 0;
    for (uint i = 0; i < N_TAPS; i++)
        if (tap_read(i)) v |= (1u << i);
    return v;
}

/* ---- rail-drop edge ring, noinit (survives reboot; R3.3) --------------- */
typedef struct {
    uint32_t t_ms;      /* 1 ms-resolution timestamp (ms since that epoch's boot) */
    uint8_t  pin_idx;   /* tap index 0-3 (555/KICK/ARM/RPOK)                      */
    uint8_t  level;     /* observed-net LOGICAL level AFTER the edge (1 = high)   */
    uint16_t epoch;     /* low 16 bits of the boot epoch that captured it         */
} tap_edge_t;

typedef struct {
    uint32_t   magic;               /* TAP_RING_MAGIC when valid                  */
    uint32_t   epoch;               /* increments each boot that ADOPTS the ring  */
    uint32_t   widx;                /* next write slot                            */
    uint32_t   count;               /* valid entries (saturates at TAP_RING_SZ)   */
    tap_edge_t ring[TAP_RING_SZ];
    uint32_t   magic2;              /* TAP_RING_MAGIC2 tail guard                 */
} tap_ring_t;

/* noinit: the crt0 zero-fill skips this section, so contents survive a watchdog
 * or soft reboot. A true power-up leaves garbage -> the magic pair fails -> zeroed. */
static tap_ring_t __uninitialized_ram(tap_ring);

static bool    tap_ring_preserved = false;  /* this boot ADOPTED a valid prior ring    */
static uint8_t tap_boot_reason    = 0;      /* 0=power/cold, 1=soft reboot, 2=watchdog */

/* IRQ storm guard state (see config.h TAP_IRQ_*) */
static uint32_t tap_irq_win_start[N_TAPS];
static uint16_t tap_irq_win_count[N_TAPS];
static uint8_t  tap_irq_muted = 0;          /* bitmask; reported in the tapdump header */
static uint32_t tap_irq_mute_ms[N_TAPS];

/* Called from IRQ context — must stay light. Records one edge. */
static void tap_ring_push(uint8_t idx, uint8_t level) {
    tap_edge_t *e = &tap_ring.ring[tap_ring.widx];
    e->t_ms    = now_ms();
    e->pin_idx = idx;
    e->level   = level;
    e->epoch   = (uint16_t)tap_ring.epoch;
    tap_ring.widx = (tap_ring.widx + 1u) % TAP_RING_SZ;
    if (tap_ring.count < TAP_RING_SZ) tap_ring.count++;
}

static void tap_irq_handler(uint gpio, uint32_t events) {
    int idx = -1;
    for (uint i = 0; i < N_TAPS; i++)
        if (tap_pins[i] == gpio) { idx = (int)i; break; }
    if (idx < 0) return;

    /* storm guard: over budget in one window -> mute THIS tap's IRQ, cooldown in
     * tap_service(). Telemetry-only loss; the safety loop never depends on taps. */
    uint32_t m = now_ms();
    if ((uint32_t)(m - tap_irq_win_start[idx]) >= TAP_IRQ_WINDOW_MS) {
        tap_irq_win_start[idx] = m;
        tap_irq_win_count[idx] = 0;
    }
    if (++tap_irq_win_count[idx] > TAP_IRQ_BUDGET) {
        gpio_set_irq_enabled(gpio, TAP_IRQ_EDGES, false);
        tap_irq_muted |= (uint8_t)(1u << idx);
        tap_irq_mute_ms[idx] = m;
        return;
    }

    uint8_t level;
    if ((events & GPIO_IRQ_EDGE_FALL) && (events & GPIO_IRQ_EDGE_RISE))
        level = tap_read((uint)idx) ? 1u : 0u;   /* coalesced double edge: current truth */
    else
        level = (events & GPIO_IRQ_EDGE_FALL) ? 1u : 0u;  /* raw fall = observed RISE (inverted) */
    tap_ring_push((uint8_t)idx, level);
}

/* Adopt or zero the noinit ring. MUST run before tap IRQs are enabled. */
static void tap_boot_init(bool wdt_reboot) {
    bool valid = (tap_ring.magic  == TAP_RING_MAGIC &&
                  tap_ring.magic2 == TAP_RING_MAGIC2 &&
                  tap_ring.widx   <  TAP_RING_SZ &&
                  tap_ring.count  <= TAP_RING_SZ);
    if (valid) {
        tap_ring.epoch++;                        /* pre- vs post-reboot edges distinguishable */
        tap_ring_preserved = true;
        /* Round-3 16-bit alias guard (Codex 2026-07-21 PM, finding 5): entries
         * store only the LOW 16 BITS of the epoch. After 65536 ring-adopting
         * reboots (a persistent watchdog crash-loop reaches that in ~9-18 h) a
         * surviving pre-loop edge's truncated tag would equal the current
         * epoch's again and tap_classify() would treat the cross-boot edge as
         * fresh. At adoption time NO entry can legitimately carry the NEW
         * current epoch's tag (IRQs are not yet enabled), so any collision is
         * definitionally stale: re-tag it to (current-1), i.e. "previous
         * epoch". The scan runs on EVERY adoption, so a re-tagged entry can
         * never age back into freshness across the 64Ki horizon either. */
        uint16_t cur16 = (uint16_t)tap_ring.epoch;
        for (uint32_t k = 0; k < tap_ring.count; k++)
            if (tap_ring.ring[k].epoch == cur16)
                tap_ring.ring[k].epoch = (uint16_t)(cur16 - 1u);
    } else {
        memset(&tap_ring, 0, sizeof tap_ring);
        tap_ring.magic  = TAP_RING_MAGIC;
        tap_ring.magic2 = TAP_RING_MAGIC2;
        tap_ring.epoch  = 1;
        tap_ring_preserved = false;
    }
    tap_boot_reason = wdt_reboot ? 2u : (tap_ring_preserved ? 1u : 0u);
    tap_irq_muted = 0;
    for (uint i = 0; i < N_TAPS; i++) { tap_irq_win_start[i] = 0; tap_irq_win_count[i] = 0; tap_irq_mute_ms[i] = 0; }
}

/* THE choke point (R3.2): the ONLY code that configures GP16-19 + GP26. Input,
 * Schmitt on (pad default — set explicitly anyway), pulls off (the board's 10k
 * drain pull-up defines the level, R1.3). GP26 goes to the ADC (digital pad off). */
static void tap_init(void) {
    for (uint i = 0; i < N_TAPS; i++) {
        uint p = tap_pins[i];
        gpio_init(p);                              /* SIO function, input, output disabled */
        gpio_set_dir(p, GPIO_IN);
        gpio_disable_pulls(p);
        gpio_set_input_hysteresis_enabled(p, true);
        force_pad_input_only(p);                   /* v1.2.2 R2-1: OEOVER=DISABLE, LAST    */
    }
    adc_init();
    adc_gpio_init(PIN_ADC_VCC5);                   /* function NULL, digital pad disabled  */
    force_pad_input_only(PIN_ADC_VCC5);            /* R2-1 (after adc_gpio_init's CTRL write) */
    adc_select_input(ADC_VCC5_INPUT);
    /* both-edge IRQ capture (R3.3); one shared callback for all four taps */
    gpio_set_irq_enabled_with_callback(tap_pins[0], TAP_IRQ_EDGES, true, &tap_irq_handler);
    for (uint i = 1; i < N_TAPS; i++)
        gpio_set_irq_enabled(tap_pins[i], TAP_IRQ_EDGES, true);
}

/* The ENFORCED half of the invariant (R3.2 + R2-1): read BACK the hardware
 * registers — SIO OE via gpio_get_dir(), IO-bank FUNCSEL via gpio_get_function(),
 * AND (v1.2.2) the CTRL.OEOVER field + live pad STATUS.OETOPAD bit via
 * pad_oe_locked() — and hard-fault if any input-contract pin can drive. The
 * v1.2.0 SIO-only readback missed the OEOVER bypass (Codex R2-1): OEOVER can
 * force output-enable at the pad with the SIO direction still reading input.
 * Coverage grew from taps+ADC to EVERY input-contract pin: taps GP16-19, ADC
 * GP26, the 8 fast inputs GP6-13, and (once read) the REV_ID straps GP20-21.
 * latch_fault() drops RP_OK via supervise(): a board whose input pins can drive
 * is REFUSED motion permission. Called at the end of init and every heartbeat
 * tick (register reads only — negligible). Fault codes: "tap_dir" = direction/
 * function drift, "pad_oe" = override/pad-level drift.                          */
static bool rev_id_inited = false;     /* REV_ID pins join the contract set after their read */

static bool tap_assert_input_only(void) {
    for (uint i = 0; i < N_TAPS; i++) {
        uint p = tap_pins[i];
#if FI1_ENABLED
        if (fi1_driving & (1u << i)) continue;   /* FI-1 bench drive in progress (deliberate) */
#endif
        if (gpio_get_dir(p) != GPIO_IN || gpio_get_function(p) != GPIO_FUNC_SIO) {
            latch_fault("tap_dir", tap_names[i]);
            return false;
        }
        if (!pad_oe_locked(p)) {
            latch_fault("pad_oe", tap_names[i]);
            return false;
        }
    }
    if (gpio_get_dir(PIN_ADC_VCC5) != GPIO_IN || gpio_get_function(PIN_ADC_VCC5) != GPIO_FUNC_NULL) {
        latch_fault("tap_dir", "ADC");
        return false;
    }
    if (!pad_oe_locked(PIN_ADC_VCC5)) {
        latch_fault("pad_oe", "ADC");
        return false;
    }
    if (inputs_inited) {                             /* fast inputs GP6-13 (R2-1 scope;
                                                      * gated like rev_id_inited: they join
                                                      * the contract set only after
                                                      * init_inputs() — round-3 fix) */
        for (size_t i = 0; i < N_INPUTS; i++) {
            uint p = inputs[i].gpio;
            if (gpio_get_dir(p) != GPIO_IN || gpio_get_function(p) != GPIO_FUNC_SIO) {
                latch_fault("tap_dir", inputs[i].id);
                return false;
            }
            if (!pad_oe_locked(p)) {
                latch_fault("pad_oe", inputs[i].id);
                return false;
            }
        }
    }
    if (rev_id_inited) {                             /* REV_ID straps GP20-21 (R2-6) */
        const uint rev_pins[2]  = { PIN_REV_ID0, PIN_REV_ID1 };
        static const char *rev_names[2] = { "REV0", "REV1" };
        for (uint i = 0; i < 2; i++) {
            uint p = rev_pins[i];
            if (gpio_get_dir(p) != GPIO_IN || gpio_get_function(p) != GPIO_FUNC_SIO) {
                latch_fault("tap_dir", rev_names[i]);
                return false;
            }
            if (!pad_oe_locked(p)) {
                latch_fault("pad_oe", rev_names[i]);
                return false;
            }
        }
    }
    return true;
}

/* ---- VCC_5V ADC (R3.4) ------------------------------------------------- */
static uint16_t adc_v5_mv = 0, adc_v5_min = 0, adc_v5_max = 0;
static bool     adc_v5_have = false;

static void adc_vcc5_sample(void) {
    uint16_t raw = adc_read();                          /* 12-bit, 3.30 V nominal ref */
    uint32_t mv  = ((uint32_t)raw * 6600u + 2047u) / 4095u;   /* x2 board divider -> mV */
    adc_v5_mv = (uint16_t)mv;
    if (!adc_v5_have) { adc_v5_min = adc_v5_max = adc_v5_mv; adc_v5_have = true; }
    else {
        if (adc_v5_mv < adc_v5_min) adc_v5_min = adc_v5_mv;
        if (adc_v5_mv > adc_v5_max) adc_v5_max = adc_v5_mv;
    }
}

/* hb interval min/max window reset — called by the MAIN-LOOP hb tick only (a
 * PING-triggered hb reports the same window; it does not reset it). */
static void adc_v5_window_reset(void) { adc_v5_min = adc_v5_max = adc_v5_mv; }

/* ---- rail-drop cause classifier (ADVISORY — R3.3 reason codes) ---------- */
/* Operates on an oldest->newest snapshot. Falling edges (level 0 after the
 * edge) of 555/ARM/RPOK within TAP_CAUSE_CLUSTER_MS of the most recent one form
 * the drop cluster; the EARLIEST faller in the cluster is the initiator:
 *   ARM  first -> "arm_drop"        (Pi deliberately/accidentally dropped ARM_PERMIT)
 *   RPOK first -> "self_health"     (our own GP2 went low first)
 *   555  first -> "kick_starvation" if no kick edge in the TAP_KICK_STARVE_MS
 *                 before it, else "555_drop" (555 fell despite a live kick train)
 * EPOCH-AWARE (v1.2.2, Codex R2-13): only entries from `cur_ep` (the epoch the
 * dump snapshot was taken in) participate — pre-reboot edges carry an older
 * epoch, their t_ms is from a DIFFERENT boot's ms clock (cross-epoch time
 * arithmetic is meaningless), and v1.2.0's epoch-blind scan let a stale
 * pre-reboot 555 fall classify a fresh, empty-this-epoch ring. Cross-epoch
 * entries remain in the dump as history (tape lines carry per-entry epochs);
 * they just can never influence a fresh cause code.                            */
static const char *tap_classify(const tap_edge_t *e, uint32_t n, uint16_t cur_ep) {
    bool     have555 = false, haveArm = false, haveRpok = false, haveKick = false;
    uint32_t t555 = 0, tArm = 0, tRpok = 0, tKick = 0;
    /* kick state AS OF the 555 fall (entries are chronological, so when the 555
     * fall is scanned, tKick holds the latest kick edge BEFORE it — a kick train
     * that resumes after a Pi reboot must not mask the starvation that caused it) */
    bool     haveKickAt555 = false;
    uint32_t tKickAt555 = 0;
    for (uint32_t k = 0; k < n; k++) {
        if (e[k].epoch != cur_ep) continue;         /* R2-13: stale pre-reboot edge — history only */
        if (e[k].pin_idx == TAP_KICK) { haveKick = true; tKick = e[k].t_ms; continue; }
        if (e[k].level != 0) continue;              /* only falling edges classify */
        switch (e[k].pin_idx) {
            case TAP_555:  have555  = true; t555  = e[k].t_ms;
                           haveKickAt555 = haveKick; tKickAt555 = tKick; break;
            case TAP_ARM:  haveArm  = true; tArm  = e[k].t_ms; break;
            case TAP_RPOK: haveRpok = true; tRpok = e[k].t_ms; break;
            default: break;
        }
    }
    (void)haveKick;
    if (!have555 && !haveArm && !haveRpok) return "none";
    uint32_t T = 0;
    if (have555  && t555  > T) T = t555;
    if (haveArm  && tArm  > T) T = tArm;
    if (haveRpok && tRpok > T) T = tRpok;
    /* earliest faller within the cluster window ending at T */
    uint32_t best_t = T + 1u; int initiator = -1;
    if (have555  && (uint32_t)(T - t555)  <= TAP_CAUSE_CLUSTER_MS && t555  < best_t) { best_t = t555;  initiator = TAP_555;  }
    if (haveRpok && (uint32_t)(T - tRpok) <= TAP_CAUSE_CLUSTER_MS && tRpok < best_t) { best_t = tRpok; initiator = TAP_RPOK; }
    if (haveArm  && (uint32_t)(T - tArm)  <= TAP_CAUSE_CLUSTER_MS && tArm  <= best_t) { best_t = tArm; initiator = TAP_ARM;  }
    if (initiator == TAP_ARM)  return "arm_drop";
    if (initiator == TAP_RPOK) return "self_health";
    if (initiator == TAP_555) {
        if (!haveKickAt555 || (uint32_t)(t555 - tKickAt555) > TAP_KICK_STARVE_MS)
            return "kick_starvation";
        return "555_drop";
    }
    return "none";   /* unreachable */
}

/* ---- TAPDUMP: drip the ring out without ever starving critical lines ---- */
#define TAPE_LINE_MAX 64u   /* worst {"ev":"tape",...} line is ~56 B */
static tap_edge_t dump_buf[TAP_RING_SZ];
static uint32_t   dump_n = 0, dump_pos = 0, dump_ep = 0;
static bool       dump_end_pending = false;

static void tap_dump_start(void) {
    uint32_t save = save_and_disable_interrupts();      /* consistent snapshot vs IRQ pushes */
    uint32_t n = tap_ring.count, w = tap_ring.widx;
    for (uint32_t k = 0; k < n; k++) {                  /* unroll oldest -> newest */
        uint32_t src = (n < TAP_RING_SZ) ? k : (w + k) % TAP_RING_SZ;
        dump_buf[k] = tap_ring.ring[src];
    }
    dump_ep = tap_ring.epoch;
    restore_interrupts(save);
    dump_n = n; dump_pos = 0; dump_end_pending = true;
    emit("{\"ev\":\"tapdump\",\"n\":%lu,\"ep\":%lu,\"br\":%u,\"mut\":%u,\"cause\":\"%s\",\"t\":%lu}\n",
         (unsigned long)dump_n, (unsigned long)dump_ep, tap_boot_reason, tap_irq_muted,
         tap_classify(dump_buf, dump_n, (uint16_t)dump_ep), (unsigned long)now_ms());
}

/* Explicit clear (the ONLY thing that empties the ring — R3.3). Keeps magic+epoch. */
static void tap_ring_clear(void) {
    uint32_t save = save_and_disable_interrupts();
    tap_ring.widx = 0;
    tap_ring.count = 0;
    restore_interrupts(save);
}

/* Main-loop service: (a) un-mute storm-guarded tap IRQs after their cooldown,
 * (b) drip queued TAPDUMP entries into the TX ring — each entry only when
 * TAPE_LINE_MAX + TXR_HEADROOM stays free, so a dump can NEVER starve hb/flt. */
static void tap_service(void) {
    if (tap_irq_muted) {
        uint32_t m = now_ms();
        for (uint i = 0; i < N_TAPS; i++) {
            uint8_t bit = (uint8_t)(1u << i);
            if ((tap_irq_muted & bit) && (uint32_t)(m - tap_irq_mute_ms[i]) >= TAP_IRQ_MUTE_MS) {
                tap_irq_win_start[i] = m;
                tap_irq_win_count[i] = 0;
                tap_irq_muted &= (uint8_t)~bit;
                gpio_set_irq_enabled(tap_pins[i], TAP_IRQ_EDGES, true);
            }
        }
    }
    while (dump_pos < dump_n || dump_end_pending) {
        if (txr_free() < (uint16_t)(TAPE_LINE_MAX + TXR_HEADROOM)) return;   /* next pass */
        if (dump_pos < dump_n) {
            const tap_edge_t *e = &dump_buf[dump_pos];
            emit("{\"ev\":\"tape\",\"i\":%lu,\"t\":%lu,\"p\":%u,\"l\":%u,\"ep\":%u}\n",
                 (unsigned long)dump_pos, (unsigned long)e->t_ms, e->pin_idx, e->level, e->epoch);
            dump_pos++;
        } else {
            emit("{\"ev\":\"tapdump_end\",\"n\":%lu}\n", (unsigned long)dump_n);
            dump_end_pending = false;
        }
    }
}

/* ---- GP19 vs GP2 self-observation cross-check (R3.1) -------------------- */
static uint8_t  rpok_mism_strikes = 0;
static uint32_t last_tapwarn_ms = 0;
static bool     tapwarn_ever = false;

/* Heartbeat-tick tap work: re-assert the direction invariant, then the RPOK
 * cross-check. Mismatch persisting TAP_RPOK_MISM_STRIKES ticks -> rate-limited
 * "tapwarn" line; escalation to a latched fault is compiled OFF by default. */
static void tap_hb_tick(void) {
    if (!tap_assert_input_only()) return;    /* latched; supervise() drops RP_OK */
    if (tap_read(TAP_RPOK) != rp_ok_state) {
        if (rpok_mism_strikes < 255u) rpok_mism_strikes++;
        if (rpok_mism_strikes >= TAP_RPOK_MISM_STRIKES) {
#if TAP_RPOK_FAULT_ENABLED
            latch_fault("tap_rpok", "RPOK");
#else
            uint32_t m = now_ms();
            if (!tapwarn_ever || (uint32_t)(m - last_tapwarn_ms) >= TAPWARN_MIN_INTERVAL_MS) {
                tapwarn_ever = true;
                last_tapwarn_ms = m;
                emit_evt("{\"ev\":\"tapwarn\",\"code\":\"rpok_mism\",\"t\":%lu}\n", (unsigned long)m);
            }
#endif
        }
    } else {
        rpok_mism_strikes = 0;
    }
}

/* ====================================================================== */
/*  v1.2.2 REV_ID strap read + identity line (Codex R2-6)                  */
/* ====================================================================== */
/* Pins/encoding: config.h REV_ID block (source: generate_kicad_netlist_revD.py
 * block_j16_protection_and_revid()). Read ONCE at init with the pull-phase
 * floating detector: a strapped pin (10k to a rail) reads the same under the
 * internal pull-down and pull-up phases; a floating pin (rev-B/rev-C board —
 * no straps fitted) follows the pull and the phases disagree -> the code is
 * REV_ID_FLOATING and the board reports "unknown", never assumed rev-D. After
 * the read the pins are left input-only, pulls off, pad-OE locked, and join
 * the tap_assert_input_only() contract set (rev_id_inited).                  */
static uint8_t pcb_rev_code = REV_ID_FLOATING;   /* 0-3 strap code, 0xFF = floating/unread */

static const char *pcb_rev_name(void) {
    switch (pcb_rev_code) {
        case REV_ID_REVD: return "revD";
        case 0x0u:        return "legacy";    /* reserved/no-strap code — NOT rev-D */
        case 0x2u:
        case 0x3u:        return "future";
        default:          return "unknown";   /* REV_ID_FLOATING / never read */
    }
}

static void rev_id_init(void) {
    const uint pins[2] = { PIN_REV_ID0, PIN_REV_ID1 };   /* bit i = pins[i] (GP21<<1|GP20) */
    uint8_t v_pd = 0, v_pu = 0;
    for (int i = 0; i < 2; i++) { gpio_init(pins[i]); gpio_set_dir(pins[i], GPIO_IN); }
    for (int i = 0; i < 2; i++) gpio_pull_down(pins[i]);
    sleep_us(REV_ID_SETTLE_US);
    for (int i = 0; i < 2; i++) if (gpio_get(pins[i])) v_pd |= (uint8_t)(1u << i);
    for (int i = 0; i < 2; i++) gpio_pull_up(pins[i]);
    sleep_us(REV_ID_SETTLE_US);
    for (int i = 0; i < 2; i++) if (gpio_get(pins[i])) v_pu |= (uint8_t)(1u << i);
    for (int i = 0; i < 2; i++) { gpio_disable_pulls(pins[i]); force_pad_input_only(pins[i]); }
    pcb_rev_code = (v_pd == v_pu) ? v_pd : REV_ID_FLOATING;
    rev_id_inited = true;                    /* pins now in the invariant contract set */
}

/* Pico unique board id, captured once as a hex string for the id line. */
static char fw_uid[2 * PICO_UNIQUE_BOARD_ID_SIZE_BYTES + 1] = "";
static void identity_init(void) { pico_get_unique_board_id_string(fw_uid, sizeof fw_uid); }

/* The additive "id" line (R2-6): PCB revision (strap-read), Pico unique id,
 * build git-describe + config.h hash (build_id.h, "unknown" on hostless
 * builds), and the FI-1 posture (FA-11 step 3: an FI-1 image must be
 * banner-identifiable). Emitted right after the boot line and on "ID". */
static void emit_id(void) {
    emit("{\"ev\":\"id\",\"fw\":\"%s\",\"pcb\":\"%s\",\"rid\":%u,\"uid\":\"%.16s\","
         "\"build\":\"%.32s\",\"cfg\":\"%.16s\",\"fi1\":%d,\"t\":%lu}\n",
         FW_VERSION, pcb_rev_name(), (unsigned)pcb_rev_code, fw_uid,
         WSL_BUILD_GIT, WSL_CFG_SHA, FI1_ENABLED ? 1 : 0, (unsigned long)now_ms());
}

#if FI1_ENABLED
/* ====================================================================== */
/*  FI-1 bench fault-injection (v1.2.2, R2-13 / R1.9) — NOT in release     */
/* ====================================================================== */
/* Everything here is compiled OUT unless -DFI1_ENABLED=1 (config.h has the
 * full gate story). fi1_jumper_present() is the physical-jumper check —
 * implemented for the target in fi1_bootsel.c (BOOTSEL button read); the
 * host test provides its own mock definition. */
bool fi1_jumper_present(void);

static void fi1_init(void) {
    if (!fi1_jumper_present()) {
        fi1_refused = true;
        latch_fault("fi1_nojumper", "");     /* re-latched forever by supervise() */
    }
}

static void fi1_release_all(void) {
    for (uint i = 0; i < N_TAPS; i++) {
        if (!(fi1_driving & (1u << i))) continue;
        uint p = tap_pins[i];
        gpio_init(p);                        /* back to SIO, input, output disabled */
        gpio_set_dir(p, GPIO_IN);
        gpio_disable_pulls(p);
        gpio_set_input_hysteresis_enabled(p, true);
        force_pad_input_only(p);
        gpio_set_irq_enabled(p, TAP_IRQ_EDGES, true);
    }
    fi1_driving = 0;
}

static void fi1_cmd(const char *s) {
    if (fi1_refused) {                       /* jumper absent: every FI1 cmd refused */
        emit("{\"ev\":\"fi1\",\"op\":\"refused\",\"t\":%lu}\n", (unsigned long)now_ms());
        return;
    }
    if (strcmp(s, "ARM") == 0) {
        fi1_armed = true;
        emit("{\"ev\":\"fi1\",\"op\":\"armed\",\"t\":%lu}\n", (unsigned long)now_ms());
    } else if (strncmp(s, "DRIVE ", 6) == 0 && s[6] >= '0' && s[6] <= '3' && s[7] == '\0') {
        if (!fi1_armed) return;              /* DRIVE before ARM is ignored */
        uint idx = (uint)(s[6] - '0');
        uint p = tap_pins[idx];
        gpio_set_irq_enabled(p, TAP_IRQ_EDGES, false);   /* no self-edge storm into the ring */
        gpio_set_oeover(p, GPIO_OVERRIDE_NORMAL);        /* unlock the pad OE (deliberate)   */
        gpio_set_dir(p, GPIO_OUT);
        gpio_put(p, 1);                                  /* FA-7 step 2: output-HIGH         */
        fi1_driving |= (uint8_t)(1u << idx);
        emit("{\"ev\":\"fi1\",\"op\":\"drive\",\"p\":%u,\"t\":%lu}\n",
             idx, (unsigned long)now_ms());
    } else if (strcmp(s, "RELEASE") == 0) {
        fi1_release_all();
        fi1_armed = false;
        bool ok = tap_assert_input_only();   /* re-verify the restored contract */
        emit("{\"ev\":\"fi1\",\"op\":\"released\",\"ok\":%d,\"t\":%lu}\n",
             ok ? 1 : 0, (unsigned long)now_ms());
    }
    /* unknown FI1 sub-commands are ignored */
}
#endif /* FI1_ENABLED */

/* ====================================================================== */
/*  Pi -> RP2040 command line protocol                                    */
/*    RUN <m>  STOP <m|*>  CLEAR  PING  TAPDUMP  TAPCLR (v1.2)  ID (v1.2.2)*/
/* ====================================================================== */
static void emit_hb(void);

static void handle_line(char *s) {
    if (strncmp(s, "RUN ", 4) == 0) {
        motor_t *mt = find_motor(s + 4);
        /* Stamp the start time ONLY on a false->true transition: a Pi that
         * re-asserts RUN must not keep resetting the max-run backstop timer. */
        if (mt && !mt->running) { mt->running = true; mt->t_start_ms = now_ms(); }
    } else if (strncmp(s, "STOP ", 5) == 0) {
        if (s[5] == '*') { motors_all_stop(); camstop_all_disarm(); }
        else {
            motor_t *mt = find_motor(s + 5);
            /* v1.1: a STOP for a guarded motor disarms its cam-stop grace window (the Pi
             * obeyed the cam edge in time) — before clearing `running`, while mt still points
             * at the motor the camstop descriptors were resolved against. */
            if (mt) { camstop_motor_stopped(mt); mt->running = false; }
        }
    } else if (strcmp(s, "CLEAR") == 0) {
        /* The Pi issues CLEAR only from a known-safe (zero/ready) state. */
        motors_all_stop();
        camstop_all_disarm();
        fault_latched = false;
        fault_code[0] = '\0';
        emit("{\"ev\":\"ack\",\"cmd\":\"CLEAR\",\"t\":%lu}\n", (unsigned long)now_ms());
    } else if (strcmp(s, "PING") == 0) {
        emit_hb();
    } else if (strcmp(s, "TAPDUMP") == 0) {
        /* v1.2: snapshot + header now; entries drip out via tap_service() */
        tap_dump_start();
    } else if (strcmp(s, "TAPCLR") == 0) {
        /* v1.2: the ONLY thing that empties the tap ring (reboot never does) */
        tap_ring_clear();
        emit("{\"ev\":\"ack\",\"cmd\":\"TAPCLR\",\"t\":%lu}\n", (unsigned long)now_ms());
    } else if (strcmp(s, "ID") == 0) {
        /* v1.2.2 (R2-6): re-emit the identity line on demand */
        emit_id();
#if FI1_ENABLED
    } else if (strncmp(s, "FI1 ", 4) == 0) {
        /* v1.2.2 bench build ONLY (R1.9): a release image has no FI1 grammar */
        fi1_cmd(s + 4);
#endif
    }
    /* unknown lines are ignored (forward-compatible) */
}

static char   line[64];
static size_t llen = 0;
static bool   rx_discard = false;   /* overrun: swallow until end-of-line */

static void poll_uart(void) {
    while (uart_is_readable(UART_ID)) {
        char c = uart_getc(UART_ID);
        if (c == '\n' || c == '\r') {
            if (!rx_discard && llen) { line[llen] = '\0'; handle_line(line); }
            llen = 0;
            rx_discard = false;     /* a line terminator always re-syncs */
        } else if (rx_discard) {
            /* swallowing the tail of an oversized/garbled line — without this,
             * the tail bytes re-accumulate and can parse as a fresh command
             * (e.g. an embedded "STOP S" or "CLEAR" inside line noise). */
        } else if (llen < sizeof(line) - 1) {
            line[llen++] = c;
        } else {
            llen = 0;               /* overrun -> drop the WHOLE line, tail included */
            rx_discard = true;
        }
    }
}

/* ====================================================================== */
/*  Heartbeat                                                             */
/* ====================================================================== */
/* Debounced input levels as a bitmask, bit i = inputs[i] asserted
 * (SA,SB,SC,TA1,TA2,TB,DIELL_L,DIELL_R = bits 0..7). Sent in every hb so the
 * Pi can RESYNC its SC/TB interlock echo from level snapshots instead of
 * trusting an edge history that a single dropped line corrupts forever. */
static unsigned input_mask(void) {
    unsigned v = 0;
    for (size_t i = 0; i < N_INPUTS; i++)
        if (inputs[i].stable_asserted) v |= (1u << i);
    return v;
}

/* Motors currently marked running, bit i = motors[i] (S,T,SP,M2,M1,BE,M = bits 0..6). */
static unsigned run_mask(void) {
    unsigned v = 0;
    for (size_t i = 0; i < N_MOTORS; i++)
        if (motors[i].running) v |= (1u << i);
    return v;
}

static void emit_hb(void) {
    /* v1.2 additive fields (R3.3/R3.4 — older Pi parsers ignore unknown keys):
     * tap = observed-net levels (bit 0..3 = 555,KICK,ARM,RPOK — POST-inversion),
     * rd = tap-ring depth, ep = ring epoch, v5/v5n/v5x = VCC_5V latest/min/max mV
     * over the current hb window. v1.2.2 (R2-6): rid = the REV_ID strap code
     * (0-3; 255 = floating/unread — a rev-D image on a strapless board is
     * visible every beat). Re-count the fmtbuf SIZE BUDGET if you add more. */
    emit("{\"ev\":\"hb\",\"ok\":%d,\"flt\":\"%s\",\"up\":%lu,\"drp\":%lu,\"in\":%u,\"run\":%u,"
         "\"tap\":%u,\"rd\":%lu,\"ep\":%lu,\"v5\":%u,\"v5n\":%u,\"v5x\":%u,\"rid\":%u}\n",
         rp_ok_state ? 1 : 0,
         fault_latched ? fault_code : "",
         (unsigned long)now_ms(),
         (unsigned long)txr_drops,
         input_mask(), run_mask(),
         tap_mask(), (unsigned long)tap_ring.count, (unsigned long)tap_ring.epoch,
         adc_v5_mv, adc_v5_min, adc_v5_max, (unsigned)pcb_rev_code);
}

/* v1.1 posture string for the boot event: "off" when the per-cam enable is 0, else
 * the configured trip edge ("f"/"r", or "?" = enabled-but-unconfirmed, which can
 * never trip). dst must hold >= 4 bytes. */
static void camstop_posture_str(char *dst, bool enabled, char trip) {
    if (!enabled) { dst[0] = 'o'; dst[1] = 'f'; dst[2] = 'f'; dst[3] = '\0'; }
    else          { dst[0] = trip; dst[1] = '\0'; }
}

/* ====================================================================== */
/*  main                                                                  */
/* ====================================================================== */
int main(void) {
#if DEBUG_USB
    stdio_init_all();   /* USB-CDC only (uart stdio disabled in CMake) */
#endif

    /* RP_OK LOW first, before anything else — fail-safe (rail stays dead during init).
     * This is the ONE deliberate exception to R3.2's "tap_init before any other GPIO
     * configuration": the fail-safe RP_OK drive is the stronger invariant, GP2 is not
     * a tap pin, and the taps are input-only from reset anyway (RP2040 pads reset with
     * output disabled) — tap_init() only ever NARROWS their configuration. */
    gpio_init(PIN_RP_OK);
    gpio_set_dir(PIN_RP_OK, GPIO_OUT);
    gpio_put(PIN_RP_OK, 0);

    /* v1.2: adopt/zero the noinit tap ring BEFORE tap IRQs can write it, then the
     * tap choke-point init — ahead of every other GPIO configuration (R3.2). */
    bool wdt_reboot = watchdog_caused_reboot();
    tap_boot_init(wdt_reboot);
    tap_init();
    rev_id_init();              /* v1.2.2 R2-6: strap read; pins then join the contract set */
    identity_init();            /* v1.2.2 R2-6: capture the Pico unique id                  */
    tap_assert_input_only();    /* enforced from the first moment (latches on drift) */

    /* uart0 to the Pi (protocol transport; NOT stdio). */
    uart_init(UART_ID, UART_BAUD);
    gpio_set_function(PIN_UART_TX, GPIO_FUNC_UART);
    gpio_set_function(PIN_UART_RX, GPIO_FUNC_UART);
    uart_set_hw_flow(UART_ID, false, false);
    uart_set_format(UART_ID, 8, 1, UART_PARITY_NONE);
    uart_set_fifo_enabled(UART_ID, true);

    init_inputs();
    tap_assert_input_only();    /* GP6-13 joined the contract set — verify immediately
                                 * (round-3 boot-order fix; the line above pre-inputs
                                 * covers taps/ADC/REV_ID only) */
    init_camstops();        /* v1.1: resolve cam-stop descriptor motor pointers + disarm */
#if FI1_ENABLED
    fi1_init();             /* v1.2.2 bench build: physical-jumper gate (permanent refusal) */
#endif
    boot_ms = now_ms();

    /* maxrun_ms: the Pi must verify its MAX_MOTION_S does not exceed this at
     * link-up (the firmware backstop is an independent compile-time copy).
     * dbg: 1 = DEBUG_USB build, so a debug image at the lane is visible.
     * v11 (v1.1.1): the v1.1 enforcement posture — an ARMED build must be
     * on-the-wire distinguishable from a stock build (FW_VERSION is identical
     * for both). sa/ta1 = "off" | the trip edge ("f"/"r"/"?"); echo/nrun =
     * INTERLOCK_ECHO_ENABLED / MOTION_NO_RUN_ENABLED.
     * tap (v1.2): noinit-ring boot semantics (R3.3) — ep = epoch, pre = 1 if a
     * valid pre-reboot ring was ADOPTED (0 = zeroed: power loss/first boot),
     * n = preserved entry count. wdt_reset (v0.2.0) is the boot-reason capture.
     * All additive fields: older Pi-side parsers ignore unknown keys. */
    char sa_p[4], ta1_p[4];
    camstop_posture_str(sa_p,  (bool)CAM_SA_STOP_ENABLED,  CAM_SA_TRIP);
    camstop_posture_str(ta1_p, (bool)CAM_TA1_STOP_ENABLED, CAM_TA1_TRIP);
    emit("{\"ev\":\"boot\",\"fw\":\"%s\",\"wdt_reset\":%d,\"rp_ok\":0,\"maxrun_ms\":%lu,\"dbg\":%d,"
         "\"v11\":{\"sa\":\"%s\",\"ta1\":\"%s\",\"echo\":%d,\"nrun\":%d},"
         "\"tap\":{\"ep\":%lu,\"pre\":%d,\"n\":%lu}}\n",
         FW_VERSION, wdt_reboot ? 1 : 0, (unsigned long)MAX_MOTION_MS, DEBUG_USB ? 1 : 0,
         sa_p, ta1_p, INTERLOCK_ECHO_ENABLED ? 1 : 0, MOTION_NO_RUN_ENABLED ? 1 : 0,
         (unsigned long)tap_ring.epoch, tap_ring_preserved ? 1 : 0,
         (unsigned long)tap_ring.count);
    emit_id();              /* v1.2.2 R2-6: identity line follows the boot line */

    /* RP2040 hardware watchdog: if the loop ever hangs, the chip resets -> GP2 goes
     * Hi-Z -> external 100k pulldown holds the rail DEAD -> motion stops. */
    watchdog_enable(WDT_TIMEOUT_MS, 1);

    uint32_t last_hb = now_ms();
    uint32_t last_adc = last_hb;

    for (;;) {
        watchdog_update();      /* keep the chip alive only while the loop runs */
        scan_inputs();          /* debounce + push cam/ball events             */
        poll_uart();            /* RUN/STOP/CLEAR/PING/TAPDUMP/TAPCLR from Pi  */
        supervise();            /* compute + drive RP_OK (fail-safe)           */
        txr_drain();            /* push queued telemetry, non-blocking         */
        tap_service();          /* v1.2: IRQ un-mute + drip tap-ring dump      */

        uint32_t m = now_ms();
        if ((uint32_t)(m - last_adc) >= ADC_VCC5_SAMPLE_MS) {   /* v1.2: 10 Hz VCC_5V */
            last_adc = m;
            adc_vcc5_sample();
        }
        if ((uint32_t)(m - last_hb) >= HB_INTERVAL_MS) {
            last_hb = m;
            tap_hb_tick();      /* v1.2: direction invariant + RPOK cross-check */
            emit_hb();
            adc_v5_window_reset();
        }
    }
    /* not reached */
}

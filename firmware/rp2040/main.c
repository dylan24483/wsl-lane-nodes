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
 *   - This board is NEVER the only safety device. The TB/SC collision interlock
 *     (J_SAFETY hardware NC loop), the Stop/CIS/master-breaker chain, the NE555
 *     watchdog (watches the *Pi*), and regenerative motor braking are all in
 *     hardware, independent of this firmware.
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
 *   - SC/TB collision echo gating RP_OK (the hardware J_SAFETY loop is primary;
 *     the firmware echo is enabled once the SC/TB windows are bench-confirmed).
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
#define TXR_SZ 512
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
static char fmtbuf[160];
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
/*  Fast inputs: time-based debounce + edge detection                     */
/* ====================================================================== */
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
    uint32_t    win_start_ms;   /* chatter-rate window start */
    uint8_t     win_edges;      /* debounced edges seen in the current window */
} input_t;

static input_t inputs[] = {
    { "SA",      PIN_SA,      DEBOUNCE_CAM_US,   false, CHATTER_MAX_CAM,   false, false, 0, 0, 0 },
    { "SB",      PIN_SB,      DEBOUNCE_CAM_US,   false, CHATTER_MAX_CAM,   false, false, 0, 0, 0 },
    { "SC",      PIN_SC,      DEBOUNCE_CAM_US,   false, CHATTER_MAX_CAM,   false, false, 0, 0, 0 },
    { "TA1",     PIN_TA1,     DEBOUNCE_CAM_US,   false, CHATTER_MAX_CAM,   false, false, 0, 0, 0 },
    { "TA2",     PIN_TA2,     DEBOUNCE_CAM_US,   false, CHATTER_MAX_CAM,   false, false, 0, 0, 0 },
    { "TB",      PIN_TB,      DEBOUNCE_CAM_US,   false, CHATTER_MAX_CAM,   false, false, 0, 0, 0 },
    { "DIELL_L", PIN_DIELL_L, DEBOUNCE_DIELL_US, true,  CHATTER_MAX_DIELL, false, false, 0, 0, 0 },
    { "DIELL_R", PIN_DIELL_R, DEBOUNCE_DIELL_US, true,  CHATTER_MAX_DIELL, false, false, 0, 0, 0 },
};
#define N_INPUTS (sizeof(inputs) / sizeof(inputs[0]))

static uint32_t last_ball_ms = 0;

static void latch_fault(const char *code, const char *motor);   /* defined below */
static void camstop_on_cam_edge(const char *cam_id, char edge); /* v1.1, defined below */

static void init_inputs(void) {
    uint64_t t = time_us_64();
    for (size_t i = 0; i < N_INPUTS; i++) {
        input_t *in = &inputs[i];
        gpio_init(in->gpio);
        gpio_set_dir(in->gpio, GPIO_IN);
        gpio_pull_up(in->gpio);                 /* belt + suspenders with the on-board 10k */
        bool asserted = (gpio_get(in->gpio) == 0);   /* active-low */
        in->stable_asserted = asserted;
        in->cand_asserted   = asserted;
        in->cand_since_us   = t;
        in->win_start_ms    = now_ms();
        in->win_edges       = 0;
    }
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
             * so the hb "in" mask stays truthful. */
            uint32_t em = now_ms();
            if ((uint32_t)(em - in->win_start_ms) >= CHATTER_WINDOW_MS) {
                in->win_start_ms = em;
                in->win_edges = 0;
            }
            if (in->win_edges < 255u) in->win_edges++;
            if (in->win_edges > in->chatter_max) {
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
         * STOP it within grace_ms or supervise() latches. Re-trips just refresh the window. */
        if (cs->enabled && cs->motor && cs->motor->running) {
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
/*  Pi -> RP2040 command line protocol                                    */
/*    RUN <m>   STOP <m|*>   CLEAR   PING                                  */
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
    emit("{\"ev\":\"hb\",\"ok\":%d,\"flt\":\"%s\",\"up\":%lu,\"drp\":%lu,\"in\":%u,\"run\":%u}\n",
         rp_ok_state ? 1 : 0,
         fault_latched ? fault_code : "",
         (unsigned long)now_ms(),
         (unsigned long)txr_drops,
         input_mask(), run_mask());
}

/* ====================================================================== */
/*  main                                                                  */
/* ====================================================================== */
int main(void) {
#if DEBUG_USB
    stdio_init_all();   /* USB-CDC only (uart stdio disabled in CMake) */
#endif

    /* RP_OK LOW first, before anything else — fail-safe (rail stays dead during init). */
    gpio_init(PIN_RP_OK);
    gpio_set_dir(PIN_RP_OK, GPIO_OUT);
    gpio_put(PIN_RP_OK, 0);

    /* uart0 to the Pi (protocol transport; NOT stdio). */
    uart_init(UART_ID, UART_BAUD);
    gpio_set_function(PIN_UART_TX, GPIO_FUNC_UART);
    gpio_set_function(PIN_UART_RX, GPIO_FUNC_UART);
    uart_set_hw_flow(UART_ID, false, false);
    uart_set_format(UART_ID, 8, 1, UART_PARITY_NONE);
    uart_set_fifo_enabled(UART_ID, true);

    init_inputs();
    init_camstops();        /* v1.1: resolve cam-stop descriptor motor pointers + disarm */
    boot_ms = now_ms();

    bool wdt_reboot = watchdog_caused_reboot();
    /* maxrun_ms: the Pi must verify its MAX_MOTION_S does not exceed this at
     * link-up (the firmware backstop is an independent compile-time copy).
     * dbg: 1 = DEBUG_USB build, so a debug image at the lane is visible. */
    emit("{\"ev\":\"boot\",\"fw\":\"%s\",\"wdt_reset\":%d,\"rp_ok\":0,\"maxrun_ms\":%lu,\"dbg\":%d}\n",
         FW_VERSION, wdt_reboot ? 1 : 0, (unsigned long)MAX_MOTION_MS, DEBUG_USB ? 1 : 0);

    /* RP2040 hardware watchdog: if the loop ever hangs, the chip resets -> GP2 goes
     * Hi-Z -> external 100k pulldown holds the rail DEAD -> motion stops. */
    watchdog_enable(WDT_TIMEOUT_MS, 1);

    uint32_t last_hb = now_ms();

    for (;;) {
        watchdog_update();      /* keep the chip alive only while the loop runs */
        scan_inputs();          /* debounce + push cam/ball events             */
        poll_uart();            /* RUN/STOP/CLEAR/PING from the Pi             */
        supervise();            /* compute + drive RP_OK (fail-safe)           */
        txr_drain();            /* push queued telemetry, non-blocking         */

        uint32_t m = now_ms();
        if ((uint32_t)(m - last_hb) >= HB_INTERVAL_MS) { last_hb = m; emit_hb(); }
    }
    /* not reached */
}

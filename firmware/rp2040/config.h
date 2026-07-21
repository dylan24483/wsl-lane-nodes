/*
 * WSL Phase 8b — RP2040 lane-controller co-processor — pin + timing + protocol contract
 *
 * AUTHORITATIVE PIN MAP SOURCE: scripts/generate_kicad_netlist_revB.py, block_rp2040()
 * (the LIVE board netlist generator). Physical Pico pin -> GPIO verified against the
 * KiCad "Module:RaspberryPi_Pico_SMD" footprint. If the board netlist changes, re-verify
 * these against block_rp2040() before flashing — do NOT trust the older draft in
 * docs/phase8_channel_allocation.md §2, which assigned the fast inputs to GP0-GP7 (WRONG
 * vs the as-built board; the real board uses GP6-GP13).
 *
 * Electrical sense (from generate_kicad_netlist_revB.py opto_input()): every fast input is
 * opto-isolated and ACTIVE-LOW at the Pico — machine contact CLOSED (signal asserted) pulls
 * the GPIO LOW; idle is HIGH (on-board 10k pull-up to 3V3). RP2040_OK (GP2) drives an NPN in
 * the relay-enable-rail AND chain: HIGH = permit motion, LOW = drop the rail. A 100k base
 * pulldown makes the rail fail-safe-dead whenever GP2 is Hi-Z (unpowered / in reset / pre-init).
 */
#ifndef WSL_PHASE8B_RP2040_CONFIG_H
#define WSL_PHASE8B_RP2040_CONFIG_H

/* v1.2.0 (2026-07-21, rev-D remediation R3 — closes Codex finding C2, NOT yet flashed):
 * GP16-19 rev-D diagnostic taps get an ENFORCED input-only init (tap_init choke point +
 * tap_assert_input_only register readback each heartbeat), inverted-tap decode (2N7002
 * common-source stage: raw pad 0 = observed net HIGH), a 1 ms-timestamped rail-drop edge
 * ring in noinit RAM (survives reboot; validity magic + epoch), and VCC_5V ADC sampling
 * on GP26. ALL ADDITIVE: v1.1 line formats unchanged, v1.1 enforcement flags still
 * DEFAULT OFF — a default build adds no NEW enforcement beyond the tap direction
 * invariant (which can only ever latch_fault, i.e. fail-safe). See CHANGELOG.md. */
#define FW_VERSION "phase8b-rp2040 v1.2.0"

/* ---- UART (uart0) link to the Pi -------------------------------------------------------- */
#define UART_BAUD     115200
#define PIN_UART_TX   0   /* GP0, Pico pin 1  -> Pi RX   (net PI_UART_RX) */
#define PIN_UART_RX   1   /* GP1, Pico pin 2  <- Pi TX   (net PI_UART_TX) */

/* ---- Rail permission output ------------------------------------------------------------- */
#define PIN_RP_OK     2   /* GP2, Pico pin 4  -> RP2040_OK; HIGH=permit motion, LOW=drop rail */

/* ---- Fast inputs (opto, ACTIVE-LOW: asserted = GPIO LOW) -------------------------------- */
#define PIN_SA        6   /* GP6,  Pico pin 9  : sweep cam  (270 run-through stop / 360 zero)  */
#define PIN_SB        7   /* GP7,  Pico pin 10 : sweep cam  (66 guard / 186 table-spot init)   */
#define PIN_SC        8   /* GP8,  Pico pin 11 : sweep-under-table interlock window (86-243)   */
#define PIN_TA1       9   /* GP9,  Pico pin 12 : table cam  (355 zero stop / 185 delay reset)  */
#define PIN_TA2      10   /* GP10, Pico pin 14 : table cam  (260 run-through / pin-latch / decn)*/
#define PIN_TB       11   /* GP11, Pico pin 15 : table-sweep interference interlock (105-255)  */
#define PIN_DIELL_L  12   /* GP12, Pico pin 16 : ball detect, left beam  (cushion SS trigger)  */
#define PIN_DIELL_R  13   /* GP13, Pico pin 17 : ball detect, right beam                       */

/* ---- v1.2 rev-D diagnostic taps (remediation spec R3, 2026-07-21) ----------------------- */
/* AUTHORITATIVE SOURCE: docs/phase8_revD_remediation_spec_2026-07-21.md §R3 (the binding
 * firmware contract) + generate_kicad_netlist_revD.py block_diag() (rev-D board only —
 * on a rev-B/rev-C board GP16-19/GP26 are UNCONNECTED and these read as floating noise;
 * the IRQ storm guard below keeps that harmless, but tap telemetry is meaningless there).
 *
 * Electrical sense (R1.2 tap front-end): each tap is a 2N7002 common-source inverter —
 * observed net HIGH -> FET on -> GPIO reads LOW. ALL FOUR TAPS ARE INVERTED. The
 * inversion happens in exactly ONE place in code (tap_read() in main.c, per R3.1); every
 * reported tap state on the wire is the post-inversion OBSERVED-NET truth.
 *
 * Direction is an ENFORCED invariant, not a convention (C2's exact complaint was that
 * "never outputs" was accidental non-use): tap_init() is the single choke-point that
 * configures these pins (input, Schmitt, no pulls — the board provides the 10k drain
 * pull-up, R1.3), and tap_assert_input_only() reads BACK the SIO OE + IO-bank function
 * registers each heartbeat tick and latch_fault()s (fail-safe: drops RP_OK) on any
 * drift. The host test (test/test_v12.c) fails the build if any code path ever puts
 * GP16-19 in an output direction or writes them.                                        */
#define PIN_TAP_555    16   /* GP16, Pico pin 21 : TAP_NE555_OUT   (INVERTED: raw 0 = 555 out HIGH) */
#define PIN_TAP_KICK   17   /* GP17, Pico pin 22 : TAP_WDOG_KICK   (INVERTED)                       */
#define PIN_TAP_ARM    18   /* GP18, Pico pin 24 : TAP_ARM_PERMIT  (INVERTED)                       */
#define PIN_TAP_RPOK   19   /* GP19, Pico pin 25 : TAP_RP2040_OK   (INVERTED; cross-checked vs GP2) */
#define PIN_ADC_VCC5   26   /* GP26/ADC0, Pico pin 31 : ADC_VCC5_SENSE = VCC_5V/2 (10k/10k divider) */
#define ADC_VCC5_INPUT  0   /* ADC mux input for GP26 */

/* VCC_5V sampling cadence (R3.4): 10 Hz; the heartbeat carries latest + min/max over the
 * hb interval so 250 ms sag events (6-coil inrush) stay visible. mV conversion assumes
 * the nominal 3.30 V ADC reference and the exact /2 divider — first-article calibrates
 * against a DMM at TP1 (±3 % gate, change spec §D).                                     */
#define ADC_VCC5_SAMPLE_MS  100u

/* Rail-drop edge ring (R3.3): both-edge GPIO IRQs on the four taps, timestamped at 1 ms
 * resolution, in a noinit RAM section that SURVIVES a Pico reboot (validity magic pair +
 * epoch counter; a true power loss zeroes it). 128 entries x 8 B = 1 KB — at the kick
 * pulse rate that is seconds of history around a drop, and edge ORDER (the diagnostic
 * payload) is preserved regardless. Cleared ONLY by the TAPCLR command, never by reboot. */
#define TAP_RING_SZ      128u
#define TAP_RING_MAGIC   0x54415052u   /* "TAPR" — noinit header validity */
#define TAP_RING_MAGIC2  0x52444E45u   /* "ENDR" — tail guard (torn-struct detection) */

/* IRQ storm guard: a floating/oscillating tap pin (e.g. this firmware flashed on a
 * rev-B/rev-C board where GP16-19 are unconnected) must never be able to starve the
 * safety loop with edge IRQs. Over budget inside one window -> that ONE tap's IRQ is
 * muted for the cooldown, then re-enabled. Telemetry-only degradation; the safety loop
 * and the other taps are unaffected. Budget 64 edges/100 ms = 640 Hz sustained — far
 * above any legitimate tap signal (the kick train is ~tens of Hz), far below a floating
 * CMOS input's oscillation.                                                              */
#define TAP_IRQ_WINDOW_MS   100u
#define TAP_IRQ_BUDGET       64u
#define TAP_IRQ_MUTE_MS    1000u

/* Rail-drop cause classification (R3.3 reason codes — ADVISORY; the Pi always gets the
 * raw ring too). Falling edges of 555/ARM/RPOK within CLUSTER_MS of the most recent one
 * form "the drop"; the earliest faller is the initiator. A 555 fall with no kick edge in
 * the preceding KICK_STARVE_MS = kick starvation.
 * TAP_KICK_STARVE_MS: VERIFY against the measured NE555 watchdog window at first
 * article (R1.9 step 5) — placeholder consistent with the ~250 ms Pi kick cadence.      */
#define TAP_CAUSE_CLUSTER_MS  1000u
#define TAP_KICK_STARVE_MS     300u

/* GP19 self-observation cross-check (R3.1): the tap's view of RP2040_OK vs our own GP2
 * output register. Mismatch persisting TAP_RPOK_MISM_STRIKES consecutive heartbeat ticks
 * (>= 500 ms — the tap analog path settles in ~45 us, R1.5) emits a rate-limited
 * "tapwarn" line. Escalating the mismatch to a latched fault is COMPILED OFF by default
 * (same posture as the v1.1 flags: a default build adds no new enforcement; also keeps a
 * rev-C board with floating GP19 from nuisance-faulting).                                */
#ifndef TAP_RPOK_FAULT_ENABLED
#define TAP_RPOK_FAULT_ENABLED 0
#endif
#define TAP_RPOK_MISM_STRIKES    2u
#define TAPWARN_MIN_INTERVAL_MS  5000u

/* ---- Debounce + timing ----------------------------------------------------------------- */
#define DEBOUNCE_CAM_US     2000u   /* cams: mechanical microswitches, 12 RPM machine -> 2ms ample */
#define DEBOUNCE_DIELL_US    500u   /* ball beam-break: faster, but still de-glitched              */
/* BALL_LOCKOUT_MS coalesces the L/R DIELL PAIR (one ball breaks both beams ms apart)
 * into one "ball" event on the TRACK-B (RP2040 -> FSM) path ONLY. It is NOT the
 * phantom-ball / machine-cycle mask. BALL-DEDUP STORY (one knob per path, see the
 * matching blocks in lane_node/lane_node.py + server/lane_node_server.py):
 *   Track A (Pi-GPIO DIELL -> scoring server): AUTHORITATIVE knob =
 *     WSL_LANE_BALL_LOCKOUT_S (lane_node.py, default 0.2 s; set ~8 s at cutover).
 *     LANE_BALL_DEDUP_S (server, default 0 = off) is only a delivery-dedup backstop.
 *   Track B (this firmware -> cycle FSM): this 300 ms pair-coalesce + the FSM's own
 *     state gating (a ball is only accepted in READY). At Track-B/scoring
 *     unification the FSM's accept decision must become the single source of truth
 *     (review 2026-06-27 finding 39).                                              */
#define BALL_LOCKOUT_MS       300u  /* L/R pair coalesce -> one ball event (see story above)       */
#define HB_INTERVAL_MS        250u  /* heartbeat cadence to the Pi                                 */
#define BOOT_SETTLE_MS        200u  /* RP_OK held LOW at least this long after boot before permit  */
#define WDT_TIMEOUT_MS        250u  /* RP2040 hardware watchdog: loop hang -> chip reset -> rail drop */

/* ---- UART robustness ---------------------------------------------------------------------- */
/* TX ring bytes reserved for the critical lines (boot/hb/flt/rp_ok/ack): cam/ball telemetry    */
/* is only enqueued while at least this much stays free, so an input flood can never starve the */
/* heartbeat or a fault report. v1.2: raised 128 -> 288 (and TXR_SZ 512 -> 1024 in main.c)      */
/* because the hb line grew tap/ring/ADC fields — 288 covers the worst flt+rp_ok+hb burst       */
/* (~60+40+170 B) that the old 128 only partially reserved for. Tap-ring dump lines use an      */
/* EXPLICIT free-space check on top of this headroom, so a dump can never starve hb/flt either. */
#define TXR_HEADROOM        288u
/* Chatter guard: more than chatter_max DEBOUNCED edges from one input inside ANY window of     */
/* this length latches a "chatter" fault naming the input (fail-safe: drops RP_OK). v1.1.1:     */
/* implemented as a TRUE SLIDING window (per-input edge-timestamp ring in main.c) — the old     */
/* tumbling window reset its count at each 100 ms boundary, so a burst straddling the boundary  */
/* needed up to 2x the budget to latch. Cams at 12 RPM produce a few edges/s (8 per 100 ms is   */
/* electrically impossible from a healthy cam); DIELL gets a looser budget because violent pin  */
/* scatter can legitimately chop the beam repeatedly.                                           */
#define CHATTER_WINDOW_MS   100u
#define CHATTER_MAX_CAM       8u
#define CHATTER_MAX_DIELL    30u

/* ---- Motion max-run backstop (the RP2040's UART-independent "cam timeout", spec §4.2) --- */
/* Matches cycle_control_8270.MAX_MOTION_S = 8.0 s. A guarded motor marked RUNNING (by the   */
/* Pi over UART) for longer than this latches a fault and drops RP_OK. BE (continuous) and M  */
/* (master/power) are NOT guarded.                                                            */
#define MAX_MOTION_MS       8000u

/* ======================================================================================== */
/*  v1.1 SAFETY SUPERVISION — cam-stop overrun, SC/TB interlock echo, motion-without-RUN     */
/* ======================================================================================== */
/*  ⚠️ BENCH-CONFIRM BEFORE ENABLING ANY OF THESE. ⚠️                                         */
/*                                                                                            */
/*  Every flag here DEFAULTS to the v0.2.0 behavior (no new enforcement). They add the        */
/*  cutover G3-gate cam-stop rail-drop and uncommanded-motion backstops the firmware was      */
/*  built to carry (spec §4.2; cutover runbook §6 Stage-6b / G3), but their correctness        */
/*  depends on the per-cam edge->angle polarity that is a DEFERRED FIELD CAPTURE               */
/*  (phase8_trackB_controller_cutover_runbook.md §3.2). Until that capture is done and the     */
/*  matching CAM_*_TRIP edge is confirmed on the bench (§12.9 with one hand-rotated cam),      */
/*  enabling these risks a wrong-polarity check that either (a) latches a fail-safe fault on   */
/*  every NORMAL stop (nuisance lane-down — SAFE direction) or (b) in the SC/TB-echo case      */
/*  fails to latch when it should (the hardware J_SAFETY NC loop is still primary, so this is  */
/*  a backstop of a backstop, never the sole device). The DEFAULT-OFF posture keeps unconfirmed*/
/*  polarity from ever weakening or nuisance-tripping the rail.                                */
/*                                                                                            */
/*  Bench/cutover sequence to ARM these (runbook §3.2 -> §6 Stage 7, per board):               */
/*    1. Hand-rotate each stop cam; record which edge ('f' = asserted/fall, 'r' = released/    */
/*       rise) is the angular ZERO-STOP trip. Motion cams (SA/SB/TA1/TA2) are normally-closed  */
/*       dry contacts; SC is N.O. and TB has NO independent signal on the metered 21/22        */
/*       chassis (SC+TB = series interlock at one node, 2026-06-27 — see                       */
/*       docs/phase8_interlock_redesign.md). The opto inverts, so the un-bench-confirmed       */
/*       DEFAULT below assumes 'f' = the trip edge                                             */
/*       (consistent with rp2040_link.RP2040Link(trip_edge="f")). VERIFY, do not assume.       */
/*    2. Set the matching CAM_*_TRIP to that edge, flip the relevant *_ENABLED to 1, rebuild.  */
/*    3. Re-run the Stage-6b cam-stop rail-drop sub-test (G3): command S/T, let the stop-cam   */
/*       trip WITHOUT a STOP, confirm {"ev":"flt","code":"cam_overrun"} + RP_OK -> LOW.         */
/*                                                                                            */
/*  These checks ONLY ever latch_fault() (fail-safe: drop RP_OK). They never permit motion,    */
/*  never bypass a fault, and never feed the watchdog — a disabled flag is exactly v0.2.0.     */

/* ---- (1) Cam-stop OVERRUN enforcement -------------------------------------------------- */
/* Per stop cam: when its TRIP edge fires while the GUARDED motor is marked RUNNING, the Pi    */
/* has STOP_GRACE_MS to send STOP <motor>. If it doesn't, the firmware latches "cam_overrun"   */
/* and drops RP_OK — a Pi-independent, per-edge stop (the runbook §0 "cam-stops are SOLELY     */
/* the RP2040's job" case). Two zero-stop cams exist (SYSTEM_REFERENCE §2 cam map):            */
/*   SA  270°/360° -> stops sweep motor S      TA1 355° -> stops table motor T                 */
/* Edge tokens: 'f' = asserted/fall, 'r' = released/rise. UNCONFIRMED sentinel '?' = a value   */
/* that can never equal a real 'f'/'r' edge, so a descriptor left at '?' can NEVER trip even   */
/* if its _ENABLED is set by mistake (belt + suspenders with the per-cam enable).              */
#define CAM_TRIP_UNCONFIRMED  '?'

/* Each flag is `#ifndef`-guarded (like DEBUG_USB) so a build can override it with -D without a
 * source edit — used by the host test's "enabled" variant (test/test_v11.c) to exercise
 * the new fault paths, and available to a per-board cutover build once §3.2 polarity is locked.
 * The DEFAULT (no -D) is always the v0.2.0 no-enforcement behavior. */

/* SA -> sweep (S). DEFAULT: disabled + UNCONFIRMED trip (no enforcement until §3.2 capture).  */
#ifndef CAM_SA_STOP_ENABLED
#define CAM_SA_STOP_ENABLED   0
#endif
#ifndef CAM_SA_TRIP
#define CAM_SA_TRIP           CAM_TRIP_UNCONFIRMED   /* set to 'f' or 'r' once bench-confirmed */
#endif
#ifndef CAM_SA_GRACE_MS
#define CAM_SA_GRACE_MS       150u                   /* STOP must arrive within this of trip   */
#endif

/* TA1 -> table (T). DEFAULT: disabled + UNCONFIRMED trip.                                      */
#ifndef CAM_TA1_STOP_ENABLED
#define CAM_TA1_STOP_ENABLED  0
#endif
#ifndef CAM_TA1_TRIP
#define CAM_TA1_TRIP          CAM_TRIP_UNCONFIRMED   /* set to 'f' or 'r' once bench-confirmed */
#endif
#ifndef CAM_TA1_GRACE_MS
#define CAM_TA1_GRACE_MS      150u
#endif

/* ---- (2) SC/TB collision-interlock echo gating RP_OK ----------------------------------- */
/* The hardware J_SAFETY NC loop is PRIMARY (SC ∧ TB both in their danger window = sweep and   */
/* table about to collide). This firmware echo is a software backstop of that loop: when both  */
/* SC and TB read asserted at once AND a motion motor is running, latch "interlock_collision"  */
/* and drop RP_OK. DEFAULT disabled until the SC/TB danger windows are bench-confirmed; the     */
/* hb "in" mask already REPORTS SC/TB levels to the Pi regardless of this flag.                 */
#ifndef INTERLOCK_ECHO_ENABLED
#define INTERLOCK_ECHO_ENABLED 0
#endif

/* ---- (3) Motion-without-RUN (uncommanded-motion) detection ----------------------------- */
/* If a stop-cam TRIP edge streams in while NO motion motor (S/T/SP/M2/M1) is marked RUNNING,   */
/* the machine is turning without the Pi having commanded it (Pi wedged / external start /      */
/* relay welded). Latch "motion_no_run" and drop RP_OK. This is the one supervision check that  */
/* works even if the Pi is fully wedged. Uses the SAME per-cam CAM_*_TRIP edges, so it is also   */
/* gated on the §3.2 polarity capture. DEFAULT disabled.                                         */
#ifndef MOTION_NO_RUN_ENABLED
#define MOTION_NO_RUN_ENABLED  0
#endif
/* A trip edge whose motor IS the cam's own guarded motor while THAT motor is running is a       */
/* normal stop, never "uncommanded". Only a trip with no motion motor running at all counts.     */

/* ---- Debug ----------------------------------------------------------------------------- */
/* When 1, event lines are mirrored to USB-CDC stdio for bench debugging (the protocol still */
/* always goes out uart0 to the Pi). Set via CMake target_compile_definitions if wanted.     */
#ifndef DEBUG_USB
#define DEBUG_USB 0
#endif

#endif /* WSL_PHASE8B_RP2040_CONFIG_H */

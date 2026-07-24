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
 * the GPIO LOW; idle is HIGH (rev-D: on-board 47k pull-up to 3V3; RP2040 internal pull
 * DISABLED so it cannot reduce the qualified resistance). RP2040_OK (GP2) drives an NPN in
 * the relay-enable-rail AND chain: HIGH = permit motion, LOW = drop the rail. A 100k base
 * pulldown makes the rail fail-safe-dead whenever GP2 is Hi-Z (unpowered / in reset / pre-init).
 */
#ifndef WSL_PHASE8B_RP2040_CONFIG_H
#define WSL_PHASE8B_RP2040_CONFIG_H

/* v1.2.3 (2026-07-23, Codex round-3 remediation R3-6 + firmware half of R3-5 — NOT flashed):
 *   - CLEAR pad-revalidation gate (R3-6): the CLEAR handler now SYNCHRONOUSLY
 *     re-runs the full input-only invariant (SIO dir + funcsel + OEOVER +
 *     OETOPAD on every contract pin) BEFORE clearing any fault — a persistent
 *     pad violation makes CLEAR a no-op answered with a "nak" line, the fault
 *     stays latched and RP_OK stays low. Closes the Codex window where CLEAR
 *     unconditionally cleared and RP_OK could reassert for up to one hb tick
 *     (250 ms) with a driveable "input" pad.
 *   - FI-1 dead-man hardening (R3-6, bench build only): arm timeout (ARM with
 *     no DRIVE auto-disarms), drive timeout (max continuous injection), UART-
 *     loss release (RX-idle link-dead detection releases injection), and a
 *     continuous dead-man ("FI1 KA" token required while driving). Every
 *     auto-release restores the locked input-only contract and re-verifies it.
 *   - Boot-epoch nonce (firmware half of R3-5): a per-boot 32-bit nonce
 *     (ROSC entropy ^ boot time, never 0) in a new additive "bn" field on the
 *     boot line, the id line AND every heartbeat — the Pi can detect a missed
 *     boot line within one hb and invalidate ALL cached identity/capability
 *     state (identity itself is re-emitted after every boot and on "ID").
 * ALL ADDITIVE line formats; no safety path weakened (the CLEAR gate only ever
 * REFUSES a recovery). See CHANGELOG.md.
 *
 * v1.2.2 (2026-07-21, Codex round-2 remediation R2-1 + R2-13 — NOT flashed):
 *   - PAD-LEVEL output lock (R2-1): CTRL.OEOVER is forced to DISABLE on every
 *     input-contract pin (taps GP16-19, ADC GP26, fast inputs GP6-13, REV_ID
 *     GP20-21) and the invariant readback now ALSO verifies the OEOVER field +
 *     the pad STATUS.OETOPAD bit — the v1.2.0/v1.2.1 check read only the SIO
 *     direction, which an OEOVER override bypasses entirely at the pad.
 *   - Epoch-aware rail-drop classifier (R2-13): tap_classify() now excludes
 *     pre-reboot (cross-epoch) ring entries — they stay in the dump as
 *     history, but can never influence a fresh cause code.
 *   - FI-1 bench fault-injection hook (R2-13/R1.9): compile-flag gated
 *     (FI1_ENABLED, default OFF = zero code compiled in), BOOTSEL-jumper +
 *     arm-command gated at runtime, drives GP16-19 output-high on command for
 *     the FA-7 unidirectionality proof. NEVER a release artifact.
 *   - Identity line (R2-6): REV_ID strap read (GP20/GP21), Pico unique ID,
 *     build git-describe + config.h hash in a new additive "id" line + hb
 *     "rid" field.
 * ALL ADDITIVE line formats; safety paths unchanged except the new fail-safe
 * pad_oe fault direction. See CHANGELOG.md.
 *
 * v1.2.1 (2026-07-21): TAP_KICK_STARVE_MS 300 -> 2000 ms — the 300 value was sized
 * against HB_INTERVAL_MS (the RP2040 heartbeat) mistaken for the Pi kick cadence; the
 * REAL Pi kick is 1 Hz, so 300 ms misclassified ~65 % of genuine 555 drops as
 * kick_starvation. Advisory-classifier-only change; no safety path touched.
 *
 * v1.2.0 (2026-07-21, rev-D remediation R3 — closes Codex finding C2, NOT yet flashed):
 * GP16-19 rev-D diagnostic taps get an ENFORCED input-only init (tap_init choke point +
 * tap_assert_input_only register readback each heartbeat), inverted-tap decode (2N7002
 * common-source stage: raw pad 0 = observed net HIGH), a 1 ms-timestamped rail-drop edge
 * ring in noinit RAM (survives reboot; validity magic + epoch), and VCC_5V ADC sampling
 * on GP26. ALL ADDITIVE: v1.1 line formats unchanged, v1.1 enforcement flags still
 * DEFAULT OFF — a default build adds no NEW enforcement beyond the tap direction
 * invariant (which can only ever latch_fault, i.e. fail-safe). See CHANGELOG.md. */
#define FW_VERSION "phase8b-rp2040 v1.2.3"

/* ---- deterministic build identity ------------------------------------------------------- */
/* CMake regenerates build_id.h at BUILD time. WSL_BUILD_ID is the variant-prefixed
 * digest of the explicit firmware source/recipe inputs, image-affecting options, clean
 * Pico SDK commit, and C compiler ID/version; WSL_CFG_SHA is exactly
 * sha256(config.h)[:16]. Repository Git state, timestamps, and unrelated dirty files are
 * excluded. release/firmware_manifest.json binds the full source/config hashes and both
 * UF2 hashes to these exact on-wire values. The fallbacks exist only for host tests/builds
 * without the generator; build:"unknown" is untraceable. */
#ifndef WSL_BUILD_ID
#define WSL_BUILD_ID "unknown"
#endif
#ifndef WSL_CFG_SHA
#define WSL_CFG_SHA "unknown"
#endif

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

/* ---- v1.2.2 REV_ID board-revision straps (Codex R2-6) ----------------------------------- */
/* AUTHORITATIVE SOURCE: generate_kicad_netlist_revD.py block_j16_protection_and_revid()
 * (committed 2026-07-21, dc56964). GP20 (Pico pin 26) = REV_ID0, 10k strap; GP21 (Pico
 * pin 27) = REV_ID1, 10k strap. ENCODING: REV_ID[1:0] = GP21<<1 | GP20.
 *   rev-D board: REV_ID0 strapped to VCC_3V3 (reads 1), REV_ID1 to GND (reads 0) = 0b01.
 *   0b00 = reserved/legacy; 0b10/0b11 = future revisions.
 * On a rev-B/rev-C board these pins are UNCONNECTED (float). Detection: read once under
 * internal pull-DOWN, once under internal pull-UP — a 10k external strap wins both times
 * (the RP2040 internal pulls are ~50-80k), a floating pin follows the pull, so differing
 * reads = floating = REV_ID_FLOATING (reported "unknown", NEVER assumed rev-D). After the
 * read, pulls are disabled (zero static strap current) and the pins join the pad-OE
 * locked input-contract set.                                                              */
#define PIN_REV_ID0      20   /* GP20, Pico pin 26 : REV_ID bit 0 (rev-D: 10k to VCC_3V3) */
#define PIN_REV_ID1      21   /* GP21, Pico pin 27 : REV_ID bit 1 (rev-D: 10k to GND)     */
#define REV_ID_REVD      0x1u /* the code THIS firmware expects on a rev-D board          */
#define REV_ID_FLOATING  0xFFu/* sentinel: pull-phase reads disagreed (no straps fitted)  */
#define REV_ID_SETTLE_US 50u  /* pull -> read settle (10k/50k node settles in ~us; ample) */

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
 * TAP_KICK_STARVE_MS sizing: the Pi's REAL kick cadence is 1 Hz (lane_node.py
 * watchdog_kick_loop(): 50 ms HIGH / 950 ms LOW), so consecutive kick EDGES from a
 * healthy Pi are up to ~950 ms apart. The threshold must sit ABOVE one full kick period
 * (or a live train gets misread as starvation ~65 % of the time) and far BELOW the
 * ~11 s NE555 timeout. 2000 ms = two fully missed kick periods: a genuine live train
 * can never trip it, a dead kick train always does long before the 555 times out.
 * (v1.2.0 shipped 300u on a WRONG premise — the ~250 ms figure was HB_INTERVAL_MS, the
 * RP2040 heartbeat, not the Pi kick cadence. Fixed 2026-07-21, review finding vs C2.)
 * VERIFY at first article (R1.9 step 5): confirm the measured NE555 window ≫ 2000 ms
 * and the observed kick edge spacing < 2000 ms.                                        */
#define TAP_CAUSE_CLUSTER_MS  1000u
#define TAP_KICK_STARVE_MS    2000u

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
/* because the hb line grew tap/ring/ADC fields. v1.2.2: 288 -> 320 — hb grew the "rid" field   */
/* (worst hb now ~184 B; worst flt+rp_ok+hb burst ~60+40+184 = 284 B — 320 restores margin).    */
/* Tap-ring dump lines use an EXPLICIT free-space check on top of this headroom, so a dump can  */
/* never starve hb/flt either.                                                                  */
#define TXR_HEADROOM        320u
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

/* ---- FI-1 bench fault-injection build (v1.2.2, Codex R2-13 / remediation spec R1.9) ---- */
/* ⛔ NEVER a release artifact. DEFAULT 0 = ZERO FI-1 code is compiled in: the FI1 command    */
/* grammar does not exist, the release image physically cannot drive a tap pin, and the host  */
/* direction-invariant gate (test_v12.c section B) enforces that. Build with -DFI1_ENABLED=1  */
/* (CMake -DFI1_BUILD=ON — separate artifact name wsl_phase8b_rp2040_FI1.uf2) ONLY for the    */
/* first-article FA-7 unidirectionality proof (drive each GP16-19 output-high in turn while   */
/* metering the observed nets). Runtime gates on top of the compile gate:                     */
/*   1. physical jumper: the Pico BOOTSEL button/jumper must be HELD at boot (R1.9: "must     */
/*      refuse to run unless a physical BOOTSEL-era jumper/flag is set") — absent, the build  */
/*      latches a PERMANENT fi1_nojumper fault (re-latched past CLEAR) and ignores FI1 cmds;  */
/*   2. arm command: "FI1 ARM" must precede any "FI1 DRIVE <0-3>"; "FI1 RELEASE" restores     */
/*      every driven pin to the locked input-only contract and re-verifies it.               */
/* The id line carries "fi1":1 so an FI-1 image is banner-identifiable (FA-11 step 3).        */
#ifndef FI1_ENABLED
#define FI1_ENABLED 0
#endif

/* v1.2.3 (R3-6) FI-1 dead-man hardening — bench build only, all four are FAIL-SAFE
 * RELEASE directions (they can only ever return a driven pin to the locked input
 * contract, never extend an injection):
 *   ARM_TIMEOUT : "FI1 ARM" with no DRIVE inside this window auto-disarms (an armed
 *                 image left on a bench cannot stay armed indefinitely).
 *   DRIVE_MAX   : hard cap on one continuous injection — the pin auto-releases even
 *                 if the operator walks away mid-FA-7.
 *   UART_IDLE   : link-dead detection — NO bytes received on uart0 for this long
 *                 while a pin is driven ⇒ the controlling host is gone ⇒ release.
 *   DEADMAN     : continuous re-arm token — while driving, an explicit "FI1 KA"
 *                 line must arrive at least this often or the injection releases.
 * The bench script sends "FI1 KA" at 1 Hz (worst gap ~1 s < both UART_IDLE and
 * DEADMAN). Every auto-release path emits {"ev":"fi1","op":"autorel","why":...}
 * and re-verifies the restored input-only contract.                              */
#ifndef FI1_ARM_TIMEOUT_MS
#define FI1_ARM_TIMEOUT_MS 10000u
#endif
#ifndef FI1_DRIVE_MAX_MS
#define FI1_DRIVE_MAX_MS   60000u
#endif
#ifndef FI1_UART_IDLE_MS
#define FI1_UART_IDLE_MS    2000u
#endif
#ifndef FI1_DEADMAN_MS
#define FI1_DEADMAN_MS      3000u
#endif

/* ---- Debug ----------------------------------------------------------------------------- */
/* When 1, event lines are mirrored to USB-CDC stdio for bench debugging (the protocol still */
/* always goes out uart0 to the Pi). Set via CMake target_compile_definitions if wanted.     */
#ifndef DEBUG_USB
#define DEBUG_USB 0
#endif

#endif /* WSL_PHASE8B_RP2040_CONFIG_H */

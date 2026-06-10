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

#define FW_VERSION "phase8b-rp2040 v0.2.0"

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

/* ---- Debounce + timing ----------------------------------------------------------------- */
#define DEBOUNCE_CAM_US     2000u   /* cams: mechanical microswitches, 12 RPM machine -> 2ms ample */
#define DEBOUNCE_DIELL_US    500u   /* ball beam-break: faster, but still de-glitched              */
#define BALL_LOCKOUT_MS       300u  /* one thrown ball -> one ball event (re-trigger lockout)      */
#define HB_INTERVAL_MS        250u  /* heartbeat cadence to the Pi                                 */
#define BOOT_SETTLE_MS        200u  /* RP_OK held LOW at least this long after boot before permit  */
#define WDT_TIMEOUT_MS        250u  /* RP2040 hardware watchdog: loop hang -> chip reset -> rail drop */

/* ---- UART robustness ---------------------------------------------------------------------- */
/* TX ring bytes reserved for the critical lines (boot/hb/flt/rp_ok/ack): cam/ball telemetry    */
/* is only enqueued while at least this much stays free, so an input flood can never starve the */
/* heartbeat or a fault report.                                                                  */
#define TXR_HEADROOM        128u
/* Chatter guard: more than chatter_max DEBOUNCED edges from one input inside this window       */
/* latches a "chatter" fault naming the input (fail-safe: drops RP_OK). Cams at 12 RPM produce  */
/* a few edges/s (8 per 100 ms is electrically impossible from a healthy cam); DIELL gets a     */
/* looser budget because violent pin scatter can legitimately chop the beam repeatedly.         */
#define CHATTER_WINDOW_MS   100u
#define CHATTER_MAX_CAM       8u
#define CHATTER_MAX_DIELL    30u

/* ---- Motion max-run backstop (the RP2040's UART-independent "cam timeout", spec §4.2) --- */
/* Matches cycle_control_8270.MAX_MOTION_S = 8.0 s. A guarded motor marked RUNNING (by the   */
/* Pi over UART) for longer than this latches a fault and drops RP_OK. BE (continuous) and M  */
/* (master/power) are NOT guarded.                                                            */
#define MAX_MOTION_MS       8000u

/* ---- Debug ----------------------------------------------------------------------------- */
/* When 1, event lines are mirrored to USB-CDC stdio for bench debugging (the protocol still */
/* always goes out uart0 to the Pi). Set via CMake target_compile_definitions if wanted.     */
#ifndef DEBUG_USB
#define DEBUG_USB 0
#endif

#endif /* WSL_PHASE8B_RP2040_CONFIG_H */

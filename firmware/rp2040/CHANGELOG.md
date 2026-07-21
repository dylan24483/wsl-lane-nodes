# WSL Phase 8b — RP2040 lane-controller firmware — CHANGELOG

All entries newest-first. "Flashed" status is tracked per entry — a written version is
NOT a deployed version. Line-format changes are ADDITIVE-ONLY by policy: the Pi-side
parser (`lane_node/rp2040_link.py`) ignores unknown JSON keys and unknown `ev` kinds.

## v1.2.0 — 2026-07-21 — rev-D diagnostic taps (remediation spec R3; closes Codex C2). NOT FLASHED.

Scope = exactly `docs/phase8_revD_remediation_spec_2026-07-21.md` §R3 (the binding
contract). Rev-D board only: on rev-B/rev-C, GP16-19/GP26 are unconnected (tap telemetry
is floating-pin noise there; the IRQ storm guard keeps that harmless).

- **Input-only init as an ENFORCED invariant (C2's exact ask).** `tap_init()` is the
  single choke-point configuring GP16-19 (input, Schmitt, pulls off — board supplies the
  10 k drain pull-up) and GP26 (ADC). `tap_assert_input_only()` reads BACK the SIO OE +
  IO-bank function registers at init and every heartbeat tick and `latch_fault("tap_dir")`s
  on drift — a board whose tap pins can drive is refused RP_OK. Host test `test/test_v12.c`
  is the direction-invariant gate: the mock SDK records every output-direction/write call
  per pin and the build FAILS if GP16-19/GP26 ever appear in one, across init + normal
  operation + every fault path; a second test tampers the mock OE register and asserts the
  readback trips.
- **Inverted tap decode (R3.1).** The rev-D 2N7002 common-source stages invert: raw pad
  LOW = observed net HIGH. `tap_read()` is the ONE inversion point; every wire-reported
  tap state is post-inversion observed-net truth. GP16=NE555_OUT, GP17=WDOG_KICK,
  GP18=ARM_PERMIT, GP19=RP2040_OK.
- **Rail-drop edge ring with reboot persistence (R3.3).** Both-edge GPIO IRQs on the four
  taps, 1 ms timestamps, 128-entry ring `{t_ms, pin, level, epoch}` in a
  `__uninitialized_ram` section (verified in the .map: `.uninitialized_data.tap_ring`,
  outside crt0's zero-fill). Boot: valid magic pair ⇒ ring ADOPTED + epoch increments
  (+ `wdt_reset` boot-reason capture); invalid ⇒ zeroed (true power loss). Cleared ONLY
  by the new `TAPCLR` command, never by reboot. New `TAPDUMP` command emits a header
  (`tapdump`: depth, epoch, boot reason, muted-IRQ mask, advisory cause code) then drips
  `tape` entries into TX headroom — an explicit free-space check means a dump can never
  starve hb/flt. Advisory cause codes from edge order: `kick_starvation` (kick train
  stops, then NE555_OUT falls), `arm_drop` (ARM_PERMIT fell first), `self_health`
  (RP2040_OK fell first), `555_drop` (555 fell despite a live kick), `none`.
- **GP19 self-observation cross-check (R3.1).** Tap-observed RP2040_OK vs our own GP2
  drive; 2 consecutive mismatched heartbeat ticks ⇒ rate-limited `tapwarn` line.
  Escalation to a latched fault is COMPILED OFF (`TAP_RPOK_FAULT_ENABLED=0` default —
  same posture as the v1.1 flags; also keeps a floating rev-C GP19 from nuisance-faulting).
- **VCC_5V ADC (R3.4).** GP26/ADC0 sampled at 10 Hz; hb carries latest + min/max mV over
  the hb window (250 ms sag events visible). Nominal 3.30 V ref + exact /2 divider
  assumed — first-article calibrates vs DMM at TP1 (±3 % gate).
- **IRQ storm guard.** Over 64 edges/100 ms on one tap mutes that tap's IRQ for 1 s
  (telemetry-only loss, reported in the tapdump header) — a floating/oscillating pin can
  never starve the safety loop.
- **Line formats (all additive):** hb gains `tap`/`rd`/`ep`/`v5`/`v5n`/`v5x`; boot gains
  `tap:{ep,pre,n}`; new `tapdump`/`tape`/`tapdump_end`/`tapwarn` events; new `TAPDUMP`/
  `TAPCLR` commands (unknown lines were already ignored). Verified against the real
  `rp2040_link.py`: self-test 38/38 unchanged, all v1.2 lines parsed/ignored cleanly with
  health state intact — no Pi-side change required.
- **Capacity re-budget for the larger lines:** `fmtbuf` 160→256, `TXR_SZ` 512→1024,
  `TXR_HEADROOM` 128→288 (now covers the full worst flt+rp_ok+hb burst). Worst lines
  re-counted: boot ~183 B, hb ~174 B.
- **Safety-critical paths untouched:** motion max-run, chatter guard, RP_OK drop
  semantics, watchdog feed placement, v1.1 supervision (still default OFF) — all
  byte-for-byte logic-identical; the only new fault sources are `tap_dir` (invariant
  drift — fail-safe direction) and the compiled-off `tap_rpok`. RP_OK-LOW-first boot
  ordering retained (deliberate, documented exception to R3.2's "taps first": GP2 is not
  a tap pin and taps are input-only from reset).
- **Verification:** host tests 64/64 (`test_main`) + 32/32 (`test_v11`) + **70/70
  (`test_v12`, new)**, all 0-warning under `-Wall -Wextra -Werror` (gcc 16.1.0); clean
  ARM cross-build via `build.ps1` (pico-sdk + xpack gcc): `.uf2` = 56 KB, 32.7 KB flash /
  5.4 KB RAM. `CMakeLists.txt` gains `hardware_adc`.
- **Bench gates (host tests CANNOT prove):** real-silicon IRQ latency + noinit
  persistence across an actual watchdog/soft reboot, ADC accuracy vs DMM,
  `TAP_KICK_STARVE_MS` vs the measured NE555 window, and R1.9 steps 2-5 (unidirectionality
  + fault-insertion + at-temperature + edge-order proof). The FI-1 fault-injection build
  (R1.9) is a SEPARATE, not-yet-written bench target — it must be excluded from any
  release artifact and refuse to run without its physical jumper; it is NOT part of v1.2.

## v1.1.1 — 2026-07-06 — review fixes (findings 37/56/58). NOT FLASHED.
Boot `v11` enforcement-posture field; cam-stop grace arms on FIRST trip only; chatter
guard became a true sliding window. Pi-side: hb `run`-mask reconciliation + `v11_posture()`.
Host tests 64/64 + 32/32.

## v1.1.0 — 2026-06-10 — v1.1 SAFETY supervision, all default OFF.
Cam-stop OVERRUN, SC/TB collision echo, motion-without-RUN — `#ifndef`-overridable flags,
per-cam UNCONFIRMED trip edges; a stock build enforces exactly v0.2.0. Host tests 61/61 + 28/28.

## v0.2.0 — 2026-06-10 — audit hardening.
RX overrun whole-line discard, duplicate-RUN timer guard, boot-settle latch across the
uint32 ms wrap, per-input chatter fault, TX headroom for critical lines, oversized-emit
whole-line drop, hb `in`/`run` masks, boot `maxrun_ms`/`dbg`.

## v0.1.0 — 2026-06-03 — initial firmware.
8 fast inputs debounced → UART edge events; RP2040_OK fail-safe rail permission;
hardware watchdog; motion max-run backstop; heartbeats. Verified cross-build + host test.

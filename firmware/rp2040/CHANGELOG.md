# WSL Phase 8b — RP2040 lane-controller firmware — CHANGELOG

All entries newest-first. "Flashed" status is tracked per entry — a written version is
NOT a deployed version. Line-format changes are ADDITIVE-ONLY by policy: the Pi-side
parser (`lane_node/rp2040_link.py`) ignores unknown JSON keys and unknown `ev` kinds.

## v1.2.3 — 2026-07-23 — Codex round-3 R3-6 + firmware half of R3-5 (CLEAR pad-revalidation, FI-1 dead-man, boot nonce). NOT FLASHED.

Scope = the round-3 firmware slice of the rev-D remediation (Codex re-audit regrade,
adversarial reproductions). All three line-format additions are ADDITIVE (`bn` key);
`rp2040_link.py` must gain the boot-nonce cache-invalidation consumer (Pi-side task —
see followups; the field is defined here and repeated on boot/id/hb).

- **R3-6 — CLEAR synchronously revalidates the input-only pads.** Pre-fix, `CLEAR`
  dropped the fault latch unconditionally and `supervise()` could reassert RP_OK for up
  to one heartbeat tick (250 ms) while a driveable "input" pad persisted — the invariant
  only re-ran at the next `tap_hb_tick()`. Now the `CLEAR` handler runs the FAIL-SAFE
  half first and unconditionally (`motors_all_stop()` + `camstop_all_disarm()`), then
  re-runs the full `tap_assert_input_only()` (SIO dir + funcsel + OEOVER field + live
  OETOPAD pad bit on taps GP16-19, ADC GP26, fast inputs GP6-13, REV_ID GP20-21) BEFORE
  clearing the latch. A persistent violation makes the recovery a strict no-op: the fault
  stays latched, RP_OK stays low, and the Pi gets a `nak` line naming the fault code. The
  fail-safe half is deliberately NOT gated (a refusal must never be less safe than an
  accept). Host test `test_v12.c` section U: clean-pad CLEAR still clears (regression
  guard); violated-pad CLEAR → nak + fault latched + RP_OK stays low; restored-pad CLEAR
  succeeds.

- **R3-6 — FI-1 dead-man hardening (bench build only).** The FI-1 fault-injection image
  gained four INDEPENDENT fail-safe auto-release paths, all supervised by `fi1_service()`
  (called every main-loop pass, after `poll_uart()` so it sees the freshest RX/KA stamps,
  before `supervise()` so a re-latch drops RP_OK the same pass): **arm timeout** (`FI1 ARM`
  with no `DRIVE` for 10 s auto-disarms), **drive timeout** (any injection older than 60 s
  releases), **UART loss** (no uart0 RX byte for 2 s while driving → the bench host is gone
  → release), and a **continuous dead-man** (`FI1 KA` token required every 3 s while
  driving, else release — catches a live link whose operator script stopped). Every
  auto-release restores the locked input-only contract and re-verifies it (`autorel` event
  with `why` + `ok`). `fi1_last_rx_ms` is now stamped on EVERY received byte (not per parsed
  line) so an overrun/garbage stream still counts as a live link. Host test `test_fi1.c`
  section E proves each release path fires, restores the pin, and (E5) that the 1 Hz bench
  KA cadence holds an injection across 10 s with no false release. `test_fi1`: 28 → **44**.

- **R3-5 (firmware half) — per-boot nonce.** The tap-ring epoch resets to 1 on power loss,
  so two cold boots are epoch-indistinguishable and a Pi that missed the boot line could
  keep trusting stale cached identity/capability state. A fresh 32-bit nonce (32 ROSC
  `randombit` reads decorrelated by 1 µs gaps, XOR the boot-time µs clock; 0 reserved =
  legacy/unknown) is sampled every boot and carried in the `bn` field on the boot line, the
  id line AND every heartbeat — a `bn` change on ANY beat is an unambiguous "rebooted since
  your cache" signal even when the boot line itself was lost. Identity is re-emitted after
  every boot and on `ID`. The Pi-side consumer (drop ALL cached identity/capability state on
  a `bn` change or boot line) is a `rp2040_link.py` task coordinated with the lane agent —
  see followups. Host test `test_v12.c` section T: nonce non-zero, differs across boots,
  consistent across id+hb of one boot, and the 0-reservation guard holds over 64 boots.

- **fmtbuf SIZE BUDGET re-counted** for the added `bn` field: worst boot ~199 B, hb ~200 B,
  id ~206 B in the 256 B buffer; TXR_HEADROOM (320) still ≥ the worst flt+rp_ok+hb burst
  (~300 B). No safety path weakened — every new path is a fail-safe RELEASE or a REFUSAL.

- **Deterministic release provenance.** `id.build` no longer uses repository-wide
  `git describe --dirty`, where an unrelated document or KiCad edit changed the firmware
  identity without changing the image. It is now a variant-prefixed digest over an explicit
  firmware source/recipe allowlist, image-affecting build options, exact clean Pico SDK
  commit, and C compiler ID/version. A different SDK/compiler therefore cannot announce
  the allowlisted runtime identity. `id.cfg` is the exact 16-character prefix of the full
  `config.h` SHA-256. `release.ps1` builds both
  Release/DEBUG_USB-off images, refuses ambient compiler flags and a dirty Pico SDK, then
  writes and verifies `release/firmware_manifest.json`: both UF2 SHA-256 values, their
  embedded `id.build`/`id.cfg`/`id.fi1`, full source/config digests, CMake caches, compiler
  versions, and clean SDK commit. The deployment allowlist contains only the release image;
  FI-1 remains bench-only. Host provenance tests pin that unrelated files do not perturb
  identity and that release/FI-1 identities are distinct.

- **Rev-D 47 kΩ fast-input contract.** `init_inputs()` now disables RP2040 internal
  pulls. Leaving the internal ~50–80 kΩ pull-up enabled in parallel would reduce the
  effective pull-up to ~24–30 kΩ and invalidate the new optocoupler sink-current margin.
  The external `Rpu_*` parts are authoritative; a missing pull-up is a board fault rather
  than something firmware masks. Diagnostic taps remain separate and continue using
  their 10 kΩ `Rtapd_*` drain pull-ups. `test_v12` now asserts all fast pulls are off.
  ⚠️ **Silicon-side status (audit note 2026-07-24):** every rev-C bench/field validation
  ran with 10 kΩ boards AND internal pulls enabled — the 47 kΩ/no-internal-pull input
  path exists only in host tests and margin math until the FA-9 loaded-minimum and
  hot-corner measurements pass on the assembled first article. Do not flash this build
  onto a 10 kΩ (rev-C) board expecting validated input thresholds.

**Build:** both ARM images rebuild clean (arm-none-eabi-gcc 13.3.1, 0 warnings on main.c):
release `wsl_phase8b_rp2040.uf2` (61.5 KB) + bench `wsl_phase8b_rp2040_FI1.uf2` (65.5 KB,
differently-named — release directory auditable by filename). Host suites: `test_main`
**64/64** · `test_v11` **32/32** · `test_v12` **140/140** (+21) · `test_fi1` **44/44** (+16),
all clean under `-Wall -Wextra -Werror` (gcc 16.1.0). **NOT flashed.**

## v1.2.2 — 2026-07-21 — Codex round-2 R2-1 + R2-13 (pad-OE lock, epoch classifier, FI-1, identity). NOT FLASHED.

Scope = the round-2 firmware slice of the rev-D remediation (Codex re-audit 2026-07-21 PM).
All line-format changes ADDITIVE; `rp2040_link.py` gains the matching id/rid consumption.

**Round-3 pre-flash fixes (Codex 2026-07-21 PM re-review; amended in place — this
version was never flashed, no image with the defects ever left the repo):**

- **Boot-order regression (critical).** The R2-1 contract set grew to include the fast
  inputs GP6-13, but `main()` runs its first `tap_assert_input_only()` pass BEFORE
  `init_inputs()` — at that moment GP6-13 are at silicon reset state (FUNCSEL=NULL, not
  SIO), so EVERY boot of the unfixed image latched a spurious `tap_dir`/SA fault and
  refused RP_OK until an operator PBZ. Fix: `inputs_inited` gate (same pattern as
  `rev_id_inited`) — the pre-inputs pass still enforces taps/ADC/REV_ID from the first
  moment, GP6-13 join the contract set when `init_inputs()` completes, and `main()` runs
  a second invariant pass immediately after so init-time drift still latches at boot.
  New host test `test_v12.c` section R replicates main()'s LITERAL boot order on
  reset-state pins (the old tests all ran `init_inputs()` before any assertion, which is
  exactly why 111/111 missed it).
- **16-bit epoch alias guard (minor).** Ring entries store only the low 16 bits of the
  32-bit boot epoch; after 65536 ring-adopting reboots (a persistent watchdog crash-loop
  reaches that in ~9-18 h) a surviving pre-loop edge's truncated tag aliased back to
  "current" and could stamp a wrong advisory cause code on a TAPDUMP. Fix: at ring
  adoption (`tap_boot_init`), any entry whose 16-bit tag collides with the NEW current
  epoch is definitionally stale (IRQs not yet enabled) and is re-tagged to previous-epoch;
  the scan runs on every adoption so nothing can age back into freshness. Host test
  section S pins the wrap, the re-tag, and that fresh edges still classify.
  `test_v12` total: 111 → **119**.

- **R2-1 — pad-level output-enable lock.** The v1.2.0/v1.2.1 input-only invariant read
  back the SIO direction + IO-bank function ONLY; the RP2040's per-pin `CTRL.OEOVER`
  field bypasses both (OEOVER=ENABLE/HIGH forces output-enable AT THE PAD with the SIO
  direction still reading input). Now: `force_pad_input_only()` (the ONE lock point,
  `gpio_set_oeover(OEOVER=DISABLE)`, called LAST in every pin-config choke point because
  `gpio_init`/`gpio_set_function` rewrite the whole CTRL register and silently clear the
  override — the mock mirrors that clearing) + `pad_oe_locked()` verifying BOTH the
  OEOVER field still reads DISABLE AND the live pad `STATUS.OETOPAD` bit reads 0, at init
  and every heartbeat tick. Coverage widened from taps+ADC to EVERY input-contract pin:
  GP16-19, GP26, fast inputs GP6-13, REV_ID GP20-21. Drift latches a fail-safe `pad_oe`
  fault (RP_OK drops). The host direction gate (`test_v12.c` section M) got the required
  **OEOVER mutation cases**: override forced HIGH (pad drives, SIO still input — the
  exact blind spot), override merely returned to NORMAL (must trip BEFORE the pad
  drives), a rogue whole-CTRL rewrite, and the same on a fast input + REV_ID pin.
- **R2-13 — epoch-aware rail-drop classifier.** `tap_classify()` now takes the dump's
  epoch and EXCLUDES cross-epoch (pre-reboot) ring entries from classification — their
  timestamps are from a different boot's ms clock, and the epoch-blind v1.2.x scan let a
  stale pre-reboot 555 fall classify (or steer) a fresh diagnosis. Stale entries remain
  in the dump as history (`tape` lines carry per-entry epochs; the Pi's own staleness
  judgment is unchanged). Host tests pin both directions: stale-only ring ⇒ `none`;
  stale ARM-fall cannot steer a fresh-epoch `kick_starvation`.
- **R2-13/R1.9 — FI-1 bench fault-injection hook (⛔ NEVER a release artifact).**
  Compile-flag gated: `FI1_ENABLED` default 0 ⇒ ZERO FI-1 code in a release image (the
  `FI1` grammar does not exist; pinned by test_v12 section Q). The bench image (CMake
  `-DFI1_BUILD=ON`) builds to a DIFFERENT artifact name (`wsl_phase8b_rp2040_FI1.uf2`),
  compiles `fi1_bootsel.c` (BOOTSEL physical-jumper gate: booted without the jumper ⇒
  PERMANENT `fi1_nojumper` fault re-latched past CLEAR, all FI1 commands answered
  `refused`), and requires `FI1 ARM` before `FI1 DRIVE <0-3>` drives one tap output-high
  for the FA-7 unidirectionality proof (`FI1 RELEASE` restores + re-verifies the locked
  contract). Driven pin is invariant-exempt while driving; all other pins stay enforced.
  New host binary `test/test_fi1.c` (28/28) proves all three gates.
- **R2-6 — identity line.** REV_ID strap read on GP20/GP21 (encoding per the committed
  netlist generator: `REV_ID[1:0] = GP21<<1|GP20`, rev-D = 0b01) with a pull-phase
  floating detector — internal pull-down read, then pull-up read; a 10k strap wins both,
  a floating (rev-B/rev-C) pin follows the pull ⇒ reads differ ⇒ `REV_ID_FLOATING`
  reported "unknown", never assumed rev-D; pulls disabled after the read (zero static
  current) and the pins join the invariant contract set. New additive
  `{"ev":"id",fw,pcb,rid,uid,build,cfg,fi1,t}` line (after boot + on the new `ID`
  command): strap-read PCB rev, Pico unique id (`pico_unique_id`), build identity
  (`build_id.h`, regenerated EVERY build by `gen_build_id.cmake`: `git describe
  --always --dirty` + sha256(config.h)[:8]; host/fallback = "unknown"), FI-1 posture.
  hb gains `rid` every beat. Pi-side: `rp2040_link.py` consumes both (stored +
  `fw_identity()`/`pcb_rev_id()` accessors + typed `fw_identity` diag record; an
  `fi1:1` image is logged as an ERROR — never allowed at a lane).
- **Capacity re-budget:** hb worst ~184 B (rid), id worst ~190 B (capped `%.Ns` fields);
  fmtbuf 256 holds; `TXR_HEADROOM` 288 → 320 (worst flt+rp_ok+hb burst ~284 B).
- **Safety-critical paths untouched:** the only new fault sources are `pad_oe`
  (fail-safe direction) and the FI-1-build-only `fi1_nojumper`. RP_OK-LOW-first boot
  ordering retained; REV_ID read happens before the boot line so identity is coherent
  from the first emission.
- **Verification:** host tests **64/64** (`test_main`) + **32/32** (`test_v11`) +
  **111/111** (`test_v12`, +40 for R2-1/R2-13/R2-6) + **28/28** (`test_fi1`, new), all
  0-warning under `-Wall -Wextra -Werror` (gcc 16.1.0). Clean ARM cross-builds:
  release `.uf2` = 60.5 KB (build_id.h verified: real git hash + config sha embedded;
  `.map` confirms `tap_ring` still in `.uninitialized_data`) and FI-1 bench
  `wsl_phase8b_rp2040_FI1.uf2` = 63 KB. Pi-side: `rp2040_link.py` self-test **45/45**,
  `tests/test_rp2040_link.py` 93/93, new `tests/test_fw_identity_line.py` (6), full
  lane-node pytest suite green.
- **Bench gates (host tests CANNOT prove):** BOOTSEL read on real silicon (flash-CS
  float window), REV_ID strap levels vs the real 10k/internal-pull divider, OEOVER
  behavior on real pads (FA-7 step 2 measures the nets), and everything already listed
  under v1.2.0.

## v1.2.1 — 2026-07-21 — TAP_KICK_STARVE_MS corrected 300 → 2000 ms. NOT FLASHED.

Advisory-classifier fix (post-remediation review finding vs the C2 work; no safety path
touched, no line-format change):

- **`TAP_KICK_STARVE_MS` 300 → 2000 ms.** The v1.2.0 value was sized against a "~250 ms
  Pi kick cadence" that does not exist — that figure was `HB_INTERVAL_MS` (the RP2040
  heartbeat) mistaken for the Pi's kick period. The real kick source
  (`lane_node/lane_node.py` `watchdog_kick_loop()`) runs at 1 Hz (50 ms HIGH / 950 ms
  LOW), so consecutive kick EDGES from a perfectly healthy Pi arrive up to ~950 ms apart
  and the 300 ms threshold classified ~65 % of genuine live-kick-train `555_drop` events
  as `kick_starvation`, misdirecting post-mortems toward the Pi/kick path. 2000 ms = two
  fully missed 1 Hz kick periods: a live train can never trip it; a dead train always
  does, far inside the ~11 s NE555 window. The config.h comment now derives the value
  from the real cadence and states both first-article VERIFY bounds (measured NE555
  window ≫ 2000 ms; observed kick edge spacing < 2000 ms).
- **Host test:** section G(a) now simulates the REAL 1 Hz kick cadence (previously
  100 ms pulses — which is why the wrong constant passed), and a new G(a2) regression
  check pins that a 555 fall landing in the normal ~950 ms inter-kick gap classifies as
  `555_drop`, NOT starvation (fails against the old 300 ms value). Suites now
  **64/64 + 32/32 + 71/71**, still `-Wall -Wextra -Werror`-clean.

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

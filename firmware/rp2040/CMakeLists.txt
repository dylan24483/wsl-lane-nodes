cmake_minimum_required(VERSION 3.13)

# Pull in the Raspberry Pi Pico SDK. Set PICO_SDK_PATH in your environment, or
# pass -DPICO_SDK_FETCH_FROM_GIT=ON to have CMake download a copy.
include(pico_sdk_import.cmake)

project(wsl_phase8b_rp2040 C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# A stock Raspberry Pi Pico module is placed on the rev-B controller board.
if (NOT PICO_BOARD)
    set(PICO_BOARD pico)
endif()

pico_sdk_init()

add_executable(wsl_phase8b_rp2040
    main.c
)

target_link_libraries(wsl_phase8b_rp2040
    pico_stdlib
    hardware_uart
    hardware_gpio
    hardware_watchdog
    hardware_adc        # v1.2: VCC_5V sense on GP26/ADC0
    pico_unique_id      # v1.2.2: board unique id in the identity line (R2-6)
)

# ---- v1.2.2 build identity (Codex R2-6) --------------------------------------
# build_id.h (WSL_BUILD_GIT = git describe --always --dirty; WSL_CFG_SHA =
# sha256(config.h)[:8]) is regenerated on EVERY build by gen_build_id.cmake —
# a build-time custom target, not configure-time, so the embedded identity can
# never go stale across commits without a reconfigure. copy_if_different keeps
# no-op regenerations from forcing a main.c rebuild.
add_custom_target(wsl_build_id ALL
    COMMAND ${CMAKE_COMMAND}
        -DSRC_DIR=${CMAKE_CURRENT_SOURCE_DIR}
        -DOUT=${CMAKE_CURRENT_BINARY_DIR}/build_id.h
        -P ${CMAKE_CURRENT_SOURCE_DIR}/gen_build_id.cmake
    BYPRODUCTS ${CMAKE_CURRENT_BINARY_DIR}/build_id.h
    COMMENT "Generating build_id.h (git describe + config.h sha256)")
add_dependencies(wsl_phase8b_rp2040 wsl_build_id)
target_include_directories(wsl_phase8b_rp2040 PRIVATE ${CMAKE_CURRENT_BINARY_DIR})
target_compile_definitions(wsl_phase8b_rp2040 PRIVATE WSL_EMBED_BUILD_ID=1)

# ---- FI-1 bench fault-injection build (v1.2.2, Codex R2-13 / spec R1.9) ------
# ⛔ NEVER a release artifact. OFF by default; -DFI1_BUILD=ON produces a
# DIFFERENTLY-NAMED image (wsl_phase8b_rp2040_FI1.uf2) that compiles the FI1
# command grammar (config.h FI1_ENABLED) + the BOOTSEL physical-jumper gate
# (fi1_bootsel.c). The release image name never carries FI-1 code, so a
# release-artifact directory can be audited by filename alone.
option(FI1_BUILD "Build the BENCH-ONLY FI-1 fault-injection image (never release)" OFF)
if (FI1_BUILD)
    target_sources(wsl_phase8b_rp2040 PRIVATE fi1_bootsel.c)
    target_compile_definitions(wsl_phase8b_rp2040 PRIVATE FI1_ENABLED=1)
    set_target_properties(wsl_phase8b_rp2040 PROPERTIES OUTPUT_NAME wsl_phase8b_rp2040_FI1)
endif()

# The Pi link uses uart0 DIRECTLY (not stdio). Keep stdio OFF uart0 so it can't
# corrupt the protocol; optional USB-CDC stdio for bench debug only.
pico_enable_stdio_uart(wsl_phase8b_rp2040 0)
pico_enable_stdio_usb(wsl_phase8b_rp2040 1)

# Optional: mirror event lines to USB-CDC for bench debugging  (cmake -DDEBUG_USB=ON ...)
option(DEBUG_USB "Mirror event lines to USB-CDC stdio" OFF)
if (DEBUG_USB)
    # PICO_STDIO_USB_STDOUT_TIMEOUT_US: cap each USB-CDC write at 1 ms (SDK
    # default is 500 ms). A connected-but-stalled USB host must never block the
    # safety loop into the 250 ms hardware watchdog and reset-loop the chip.
    target_compile_definitions(wsl_phase8b_rp2040 PRIVATE
        DEBUG_USB=1
        PICO_STDIO_USB_STDOUT_TIMEOUT_US=1000)
endif()

# Produce wsl_phase8b_rp2040.uf2 (drag-drop flash) + .elf/.bin/.hex/.map
pico_add_extra_outputs(wsl_phase8b_rp2040)

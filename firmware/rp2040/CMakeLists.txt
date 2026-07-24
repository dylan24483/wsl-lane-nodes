cmake_minimum_required(VERSION 3.13)

# Pull in the Raspberry Pi Pico SDK. Set PICO_SDK_PATH in your environment, or
# pass -DPICO_SDK_FETCH_FROM_GIT=ON to have CMake download a copy.
include(pico_sdk_import.cmake)

project(wsl_phase8b_rp2040 C CXX ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)
find_package(Python3 REQUIRED COMPONENTS Interpreter)
find_package(Git QUIET)

# A stock Raspberry Pi Pico module is placed on the rev-B controller board.
if (NOT PICO_BOARD)
    set(PICO_BOARD pico)
endif()

pico_sdk_init()

# Runtime identity must distinguish binaries produced from a different SDK or
# compiler, because the lane can observe id.build/id.cfg but cannot hash flash.
set(WSL_PICO_SDK_COMMIT "unversioned")
if (Git_FOUND AND EXISTS "${PICO_SDK_PATH}/.git")
    execute_process(
        COMMAND "${GIT_EXECUTABLE}" -C "${PICO_SDK_PATH}" rev-parse HEAD
        OUTPUT_VARIABLE WSL_PICO_SDK_COMMIT
        OUTPUT_STRIP_TRAILING_WHITESPACE
        RESULT_VARIABLE WSL_SDK_GIT_RC)
    if (NOT WSL_SDK_GIT_RC EQUAL 0 OR WSL_PICO_SDK_COMMIT STREQUAL "")
        set(WSL_PICO_SDK_COMMIT "unversioned")
    else()
        execute_process(
            COMMAND "${GIT_EXECUTABLE}" -C "${PICO_SDK_PATH}" status
                    --porcelain --untracked-files=all
            OUTPUT_VARIABLE WSL_PICO_SDK_DIRTY
            OUTPUT_STRIP_TRAILING_WHITESPACE)
        if (NOT WSL_PICO_SDK_DIRTY STREQUAL "")
            string(APPEND WSL_PICO_SDK_COMMIT "-dirty")
        endif()
    endif()
endif()
set(WSL_C_COMPILER_ID "${CMAKE_C_COMPILER_ID}-${CMAKE_C_COMPILER_VERSION}")

# These options are identity inputs and must be resolved before build_id.h.
option(FI1_BUILD "Build the BENCH-ONLY FI-1 fault-injection image (never release)" OFF)
option(DEBUG_USB "Mirror event lines to USB-CDC stdio" OFF)
if (FI1_BUILD)
    set(WSL_BUILD_VARIANT fi1)
else()
    set(WSL_BUILD_VARIANT release)
endif()
if (NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Debug)
endif()

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

# ---- deterministic release identity ------------------------------------------
# build_id.h is regenerated at BUILD time from an explicit firmware-input
# allowlist, image-affecting options, clean Pico SDK commit, and C compiler
# ID/version. Repository Git state, timestamps, and unrelated files are not
# inputs.
add_custom_target(wsl_build_id ALL
    COMMAND ${CMAKE_COMMAND}
        -DSRC_DIR=${CMAKE_CURRENT_SOURCE_DIR}
        -DOUT=${CMAKE_CURRENT_BINARY_DIR}/build_id.h
        -DPYTHON=${Python3_EXECUTABLE}
        -DVARIANT=${WSL_BUILD_VARIANT}
        -DDEBUG_USB=${DEBUG_USB}
        -DPICO_BOARD=${PICO_BOARD}
        -DBUILD_TYPE=${CMAKE_BUILD_TYPE}
        -DSDK_COMMIT=${WSL_PICO_SDK_COMMIT}
        -DC_COMPILER_ID=${WSL_C_COMPILER_ID}
        -P ${CMAKE_CURRENT_SOURCE_DIR}/gen_build_id.cmake
    BYPRODUCTS ${CMAKE_CURRENT_BINARY_DIR}/build_id.h
    COMMENT "Generating deterministic controlled-input build_id.h")
add_dependencies(wsl_phase8b_rp2040 wsl_build_id)
target_include_directories(wsl_phase8b_rp2040 PRIVATE ${CMAKE_CURRENT_BINARY_DIR})
target_compile_definitions(wsl_phase8b_rp2040 PRIVATE WSL_EMBED_BUILD_ID=1)

# ---- FI-1 bench fault-injection build (v1.2.2, Codex R2-13 / spec R1.9) ------
# ⛔ NEVER a release artifact. OFF by default; -DFI1_BUILD=ON produces a
# DIFFERENTLY-NAMED image (wsl_phase8b_rp2040_FI1.uf2) that compiles the FI1
# command grammar (config.h FI1_ENABLED) + the BOOTSEL physical-jumper gate
# (fi1_bootsel.c). The release image name never carries FI-1 code, so a
# release-artifact directory can be audited by filename alone.
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

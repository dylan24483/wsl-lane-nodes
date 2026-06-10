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
)

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

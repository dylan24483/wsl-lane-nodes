/*
 * fi1_bootsel.c — FI-1 physical-jumper gate (v1.2.2, Codex R2-13 / spec R1.9)
 * ===========================================================================
 * Compiled ONLY into the bench-only FI-1 image (CMake -DFI1_BUILD=ON). The
 * remediation spec requires the fault-injection build to "refuse to run unless
 * a physical BOOTSEL-era jumper/flag is set": the gate is the Pico's BOOTSEL
 * button (or a jumper across it) HELD at boot — nothing a production deploy
 * can leave set by accident, and nothing software can set at all.
 *
 * Read technique: the standard Raspberry Pi "bb_get_bootsel_button" sequence
 * (pico-examples, picoboard/button). BOOTSEL shares the flash chip-select
 * (QSPI CS) line, so the CS output is briefly floated (OEOVER=LOW) and the pin
 * sampled — pressed/jumpered pulls it low. Flash is unusable during the
 * window, so this function MUST run from RAM (__no_inline_not_in_flash_func)
 * with interrupts off. Called ONCE at init, before the watchdog is armed and
 * before any UART traffic matters.
 *
 * The host test (test/test_fi1.c) supplies its own mock definition instead of
 * this file.
 */
#include "pico/stdlib.h"
#include "hardware/gpio.h"
#include "hardware/sync.h"
#include "hardware/structs/ioqspi.h"
#include "hardware/structs/sio.h"

bool fi1_jumper_present(void);

bool __no_inline_not_in_flash_func(fi1_jumper_present)(void) {
    const uint CS_PIN_INDEX = 1;                     /* QSPI SS = BOOTSEL */
    uint32_t flags = save_and_disable_interrupts();
    /* Float the flash CS so the button/jumper level is readable. */
    hw_write_masked(&ioqspi_hw->io[CS_PIN_INDEX].ctrl,
                    GPIO_OVERRIDE_LOW << IO_QSPI_GPIO_QSPI_SCLK_CTRL_OEOVER_LSB,
                    IO_QSPI_GPIO_QSPI_SCLK_CTRL_OEOVER_BITS);
    /* ~1-2 us settle; must not touch flash here (we ARE flash-resident code
     * otherwise — hence the not_in_flash attribute). */
    for (volatile int i = 0; i < 1000; ++i)
        ;
    /* Pressed/jumpered = pulled LOW. */
    bool present = !(sio_hw->gpio_hi_in & (1u << CS_PIN_INDEX));
    /* Restore the CS override and resume normal flash operation. */
    hw_write_masked(&ioqspi_hw->io[CS_PIN_INDEX].ctrl,
                    GPIO_OVERRIDE_NORMAL << IO_QSPI_GPIO_QSPI_SCLK_CTRL_OEOVER_LSB,
                    IO_QSPI_GPIO_QSPI_SCLK_CTRL_OEOVER_BITS);
    restore_interrupts(flags);
    return present;
}

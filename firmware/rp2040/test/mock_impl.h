/*
 * Shared host-test mock STATE + BODIES for the Pico SDK surface (see mock_pico.h for the
 * declarations). Include this exactly once per test translation unit, BEFORE `#include`-ing
 * ../main.c. Factored out of test_main.c so both the default test (test_main.c) and the
 * v1.1-enabled test (test_v11.c) share one implementation — they must never drift, since the
 * point of the second binary is to exercise the SAME firmware with the safety flags -D'd on.
 */
#ifndef MOCK_IMPL_H
#define MOCK_IMPL_H

#include "mock_pico.h"
#include <string.h>

/* ---- mock state ---------------------------------------------------------- */
uint64_t mock_us = 0;
int      mock_gpio_in[40];
int      mock_gpio_out[40];
bool     mock_uart_writable = true;
char     mock_rx[1024];
int      mock_rx_head = 0, mock_rx_tail = 0;
char     mock_tx[8192];
int      mock_tx_len = 0;
/* v1.2 */
int      mock_gpio_dir[40];
int      mock_gpio_funcsel[40];
int      mock_dir_out_calls[40];
int      mock_put_calls[40];
uint32_t mock_irq_mask[40];
gpio_irq_callback_t mock_irq_cb = 0;
uint16_t mock_adc_raw = 0;
int      mock_adc_selected = -1;
int      mock_adc_inited = 0;
/* v1.2.2 */
int      mock_gpio_oeover[40];          /* GPIO_OVERRIDE_NORMAL (0) by default */
int      mock_gpio_floating[40];
int      mock_gpio_pull[40];
char     mock_unique_id[17] = "E66038B713952A31";
mock_io_bank0_t mock_iobank0;

/* ---- mock bodies --------------------------------------------------------- */
/* v1.2: direction + function are now RECORDED (the C2 direction-invariant test
 * asserts the tap pins never see an output call), matching real-SDK semantics:
 * gpio_init() = SIO function, input, output disabled.
 * v1.2.2 (R2-1): the mock now maintains the IO_BANK0 CTRL.OEOVER field + the
 * live STATUS.OETOPAD bit with real-SDK semantics — in particular, ANY whole-
 * CTRL rewrite (gpio_init / gpio_set_function / adc_gpio_init) clears OEOVER
 * back to NORMAL, so a choke point that locks the pad BEFORE its last CTRL
 * write is caught by the tests exactly as it would be on silicon.              */
static void mock_recompute_oe(uint pin) {
    int oe;
    switch (mock_gpio_oeover[pin]) {
        case GPIO_OVERRIDE_LOW:    oe = 0; break;
        case GPIO_OVERRIDE_HIGH:   oe = 1; break;
        case GPIO_OVERRIDE_INVERT: oe = !(mock_gpio_funcsel[pin] == GPIO_FUNC_SIO
                                          && mock_gpio_dir[pin] == 1); break;
        default:                   oe = (mock_gpio_funcsel[pin] == GPIO_FUNC_SIO
                                          && mock_gpio_dir[pin] == 1); break;
    }
    mock_iobank0.io[pin].ctrl =
        (mock_iobank0.io[pin].ctrl & ~IO_BANK0_GPIO0_CTRL_OEOVER_BITS)
        | ((uint32_t)mock_gpio_oeover[pin] << IO_BANK0_GPIO0_CTRL_OEOVER_LSB);
    if (oe) mock_iobank0.io[pin].status |=  IO_BANK0_GPIO0_STATUS_OETOPAD_BITS;
    else    mock_iobank0.io[pin].status &= ~IO_BANK0_GPIO0_STATUS_OETOPAD_BITS;
}
void gpio_init(uint pin)                 { mock_gpio_dir[pin] = GPIO_IN; mock_gpio_funcsel[pin] = GPIO_FUNC_SIO;
                                           mock_gpio_oeover[pin] = GPIO_OVERRIDE_NORMAL;  /* whole-CTRL write */
                                           mock_gpio_pull[pin] = 0; mock_recompute_oe(pin); }
void gpio_set_dir(uint pin, bool out)    { mock_gpio_dir[pin] = out ? 1 : 0; if (out) mock_dir_out_calls[pin]++;
                                           mock_recompute_oe(pin); }
void gpio_pull_up(uint pin)              { mock_gpio_pull[pin] = 1; }
void gpio_pull_down(uint pin)            { mock_gpio_pull[pin] = -1; }
bool gpio_get(uint pin)                  { if (mock_gpio_floating[pin]) return mock_gpio_pull[pin] > 0;
                                           return mock_gpio_in[pin] != 0; }
void gpio_put(uint pin, bool v)          { mock_gpio_out[pin] = v ? 1 : 0; mock_put_calls[pin]++; }
void gpio_set_function(uint pin, int fn) { mock_gpio_funcsel[pin] = fn;
                                           mock_gpio_oeover[pin] = GPIO_OVERRIDE_NORMAL;  /* whole-CTRL write */
                                           mock_recompute_oe(pin); }
void gpio_set_oeover(uint pin, uint value) { mock_gpio_oeover[pin] = (int)value; mock_recompute_oe(pin); }
void sleep_us(uint64_t us)               { mock_us += us; }
void pico_get_unique_board_id_string(char *buf, uint len) {
    uint i = 0;
    for (; i + 1u < len && mock_unique_id[i]; i++) buf[i] = mock_unique_id[i];
    buf[i] = 0;
}
/* v1.2 tap surface */
uint gpio_get_dir(uint pin)              { return (uint)mock_gpio_dir[pin]; }
uint gpio_get_function(uint pin)         { return (uint)mock_gpio_funcsel[pin]; }
void gpio_disable_pulls(uint pin)        { mock_gpio_pull[pin] = 0; }
void gpio_set_input_hysteresis_enabled(uint pin, bool enabled) { (void)pin; (void)enabled; }
void gpio_set_irq_enabled(uint pin, uint32_t events, bool enabled) {
    mock_irq_mask[pin] = enabled ? events : 0u;
}
void gpio_set_irq_enabled_with_callback(uint pin, uint32_t events, bool enabled,
                                        gpio_irq_callback_t cb) {
    mock_irq_cb = cb;
    gpio_set_irq_enabled(pin, events, enabled);
}
void     adc_init(void)                  { mock_adc_inited = 1; }
void     adc_gpio_init(uint pin)         { mock_gpio_dir[pin] = GPIO_IN;
                                           gpio_set_function(pin, GPIO_FUNC_NULL); /* whole-CTRL write (v1.2.2) */ }
void     adc_select_input(uint input)    { mock_adc_selected = (int)input; }
uint16_t adc_read(void)                  { return mock_adc_raw; }
uint32_t save_and_disable_interrupts(void) { return 0; }
void     restore_interrupts(uint32_t status) { (void)status; }

uint uart_init(uart_inst_t *u, uint b)                                  { (void)u; return b; }
void uart_set_hw_flow(uart_inst_t *u, bool c, bool r)                   { (void)u; (void)c; (void)r; }
void uart_set_format(uart_inst_t *u, uint d, uint s, uart_parity_t p)   { (void)u; (void)d; (void)s; (void)p; }
void uart_set_fifo_enabled(uart_inst_t *u, bool e)                      { (void)u; (void)e; }
bool uart_is_writable(uart_inst_t *u)                                   { (void)u; return mock_uart_writable; }
bool uart_is_readable(uart_inst_t *u)                                   { (void)u; return mock_rx_head != mock_rx_tail; }
char uart_getc(uart_inst_t *u) {
    (void)u;
    char c = mock_rx[mock_rx_tail];
    mock_rx_tail = (mock_rx_tail + 1) % (int)sizeof(mock_rx);
    return c;
}
void uart_putc_raw(uart_inst_t *u, char c) {
    (void)u;
    if (mock_tx_len < (int)sizeof(mock_tx) - 1) mock_tx[mock_tx_len++] = c;
}
void watchdog_enable(uint32_t ms, bool p) { (void)ms; (void)p; }
void watchdog_update(void)                {}
bool watchdog_caused_reboot(void)         { return false; }
bool stdio_init_all(void)                 { return true; }

/* ---- harness helpers (mock-state only) ----------------------------------- */
static void rx_feed(const char *s) {
    for (; *s; s++) { mock_rx[mock_rx_head] = *s; mock_rx_head = (mock_rx_head + 1) % (int)sizeof(mock_rx); }
}
static void tx_reset(void) { mock_tx_len = 0; mock_tx[0] = 0; }
static int  tx_has(const char *sub) { mock_tx[mock_tx_len] = 0; return strstr(mock_tx, sub) != NULL; }
static void advance_us(uint64_t d) { mock_us += d; }
static void advance_ms(uint32_t d) { mock_us += (uint64_t)d * 1000u; }
static void all_idle(void) { for (int i = 0; i < 40; i++) mock_gpio_in[i] = 1; }

#endif /* MOCK_IMPL_H */

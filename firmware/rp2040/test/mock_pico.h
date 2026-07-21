/*
 * Host-test mock of the Pico SDK surface used by main.c.
 * Lets the firmware's pure logic (TX ring, debounce, RP_OK supervisor, protocol
 * parser) compile + run on a host C compiler with no hardware. See test_main.c.
 */
#ifndef MOCK_PICO_H
#define MOCK_PICO_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

typedef unsigned int uint;
typedef uint64_t absolute_time_t;            /* mock: microseconds */
typedef struct uart_inst uart_inst_t;
#define uart0 ((uart_inst_t *)0)

#define GPIO_FUNC_UART 2
#define GPIO_FUNC_SIO  5
#define GPIO_FUNC_NULL 0x1f
#define GPIO_IN  0
#define GPIO_OUT 1
#define GPIO_IRQ_EDGE_FALL 0x4u
#define GPIO_IRQ_EDGE_RISE 0x8u
typedef enum { UART_PARITY_NONE = 0 } uart_parity_t;
typedef void (*gpio_irq_callback_t)(uint gpio, uint32_t event_mask);

/* v1.2: noinit-section attribute is meaningless on the host — storage is a
 * plain static that PERSISTS across tap_boot_init() calls, which is exactly
 * the semantics the reboot-persistence tests exercise. */
#define __uninitialized_ram(group) group

/* ---- mock state (defined in mock_impl.h) ---------------------------------- */
extern uint64_t mock_us;            /* fake clock (microseconds)               */
extern int      mock_gpio_in[40];   /* gpio_get(): 1 = high/idle, 0 = low/asserted */
extern int      mock_gpio_out[40];  /* gpio_put() records here                 */
extern bool     mock_uart_writable; /* uart_is_writable() returns this         */
extern char     mock_rx[1024];      /* bytes the "Pi" sends to the firmware    */
extern int      mock_rx_head, mock_rx_tail;
extern char     mock_tx[8192];      /* bytes the firmware sent (captured)      */
extern int      mock_tx_len;
/* v1.2 direction-invariant instrumentation (C2): every direction/write call is
 * recorded PER PIN so a test can assert the tap pins NEVER appear in one.      */
extern int      mock_gpio_dir[40];      /* last gpio_set_dir() value (0=in,1=out) */
extern int      mock_gpio_funcsel[40];  /* last function set (SIO/UART/NULL/...)  */
extern int      mock_dir_out_calls[40]; /* count of gpio_set_dir(pin, GPIO_OUT)   */
extern int      mock_put_calls[40];     /* count of gpio_put(pin, ...)            */
extern uint32_t mock_irq_mask[40];      /* per-pin enabled IRQ event mask         */
extern gpio_irq_callback_t mock_irq_cb; /* registered shared IRQ callback         */
extern uint16_t mock_adc_raw;           /* adc_read() returns this                */
extern int      mock_adc_selected;      /* last adc_select_input()                */
extern int      mock_adc_inited;        /* adc_init() called                      */

/* ---- clock (header-inline; one def per TU) -------------------------------- */
static inline uint32_t to_ms_since_boot(absolute_time_t t) { return (uint32_t)(t / 1000u); }
static inline absolute_time_t get_absolute_time(void)      { return mock_us; }
static inline uint64_t time_us_64(void)                    { return mock_us; }

/* ---- SDK functions main.c calls (bodies in mock_impl.h) ------------------- */
void gpio_init(uint pin);
void gpio_set_dir(uint pin, bool out);
void gpio_pull_up(uint pin);
bool gpio_get(uint pin);
void gpio_put(uint pin, bool v);
void gpio_set_function(uint pin, int fn);
/* v1.2 tap surface */
uint gpio_get_dir(uint pin);            /* reads back the mock SIO OE state    */
uint gpio_get_function(uint pin);       /* reads back the mock IO-bank funcsel */
void gpio_disable_pulls(uint pin);
void gpio_set_input_hysteresis_enabled(uint pin, bool enabled);
void gpio_set_irq_enabled(uint pin, uint32_t events, bool enabled);
void gpio_set_irq_enabled_with_callback(uint pin, uint32_t events, bool enabled,
                                        gpio_irq_callback_t cb);
void     adc_init(void);
void     adc_gpio_init(uint pin);
void     adc_select_input(uint input);
uint16_t adc_read(void);
uint32_t save_and_disable_interrupts(void);
void     restore_interrupts(uint32_t status);

uint uart_init(uart_inst_t *u, uint baud);
void uart_set_hw_flow(uart_inst_t *u, bool cts, bool rts);
void uart_set_format(uart_inst_t *u, uint data, uint stop, uart_parity_t parity);
void uart_set_fifo_enabled(uart_inst_t *u, bool enabled);
bool uart_is_writable(uart_inst_t *u);
bool uart_is_readable(uart_inst_t *u);
char uart_getc(uart_inst_t *u);
void uart_putc_raw(uart_inst_t *u, char c);

void watchdog_enable(uint32_t ms, bool pause_on_debug);
void watchdog_update(void);
bool watchdog_caused_reboot(void);

bool stdio_init_all(void);

#endif /* MOCK_PICO_H */

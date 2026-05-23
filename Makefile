# NIC DMD — Makefile
# ===================
# Targets:
#   make          — sestaví sdílenou knihovnu (.so) i statickou (.a)
#   make test     — zkompiluje a spustí C test
#   make python   — otestuje Python implementaci
#   make all      — vše výše
#   make clean    — smaže výstupy

CC      = gcc
CFLAGS  = -Wall -Wextra -O2 -std=c99
SRCS    = nic_dmd.c
HDRS    = nic_dmd.h
OBJ     = nic_dmd.o

# Sdílená knihovna (pro Python ctypes nebo jiné jazyky)
SO      = nic_dmd.so
# Statická knihovna (pro embedded / přímé linkování)
AR_LIB  = libnic_dmd.a
# Test binárka
TEST    = nic_dmd_test

.PHONY: all so static test python clean

all: so static test python

so: $(SO)

static: $(AR_LIB)

$(OBJ): $(SRCS) $(HDRS)
	$(CC) $(CFLAGS) -fPIC -c -o $@ $<

$(SO): $(OBJ)
	$(CC) -shared -o $@ $<
	@echo "Sdílená knihovna: $(SO)"

$(AR_LIB): $(OBJ)
	ar rcs $@ $<
	@echo "Statická knihovna: $(AR_LIB)"

$(TEST): nic_dmd_test.c $(SRCS) $(HDRS)
	$(CC) $(CFLAGS) -o $@ nic_dmd_test.c $(SRCS)
	@echo "Test binárka: $(TEST)"

test: $(TEST)
	@echo ""
	@echo "=== C testy ==="
	./$(TEST)

python:
	@echo ""
	@echo "=== Python testy ==="
	python3 nic_dmd_test.py

clean:
	rm -f $(OBJ) $(SO) $(AR_LIB) $(TEST)
	@echo "Vyčištěno."

# Arduino — jen zkopíruj nic_dmd.c a nic_dmd.h do složky projektu
# AVR — přidej: CFLAGS += -mmcu=atmega328p -DF_CPU=16000000UL

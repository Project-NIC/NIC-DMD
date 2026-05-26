CC = gcc
CFLAGS = -Wall -Wextra -O3 -std=c99

TARGET = dmd_test
OBJS = nic_dmd.o nic_dmd_test.o

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^

nic_dmd.o: nic_dmd.c nic_dmd.h
	$(CC) $(CFLAGS) -c $< -o $@

nic_dmd_test.o: nic_dmd_test.c nic_dmd.h
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f $(OBJS) $(TARGET)

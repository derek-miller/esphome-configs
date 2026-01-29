# ESPHome Device Management Makefile
#
# Usage:
#   make discover              - Find devices and generate config
#   make list                  - List configured devices
#   make run IP=192.168.2.x    - Compile and upload to device
#   make logs IP=192.168.2.x   - View logs from device
#   make run-all               - Run against all configured devices
#   make run-config CONFIG=x.yaml - Run against all devices for a config
#
# Config format (devices.conf):
#   [config-file.yaml]
#   192.168.2.100
#   192.168.2.101

SHELL := /bin/bash
CONFIG_FILE := devices.conf
SCRIPTS_DIR := scripts

.PHONY: help discover list run upload logs validate compile run-all run-config logs-config validate-all clean

help:
	@echo "ESPHome Device Management"
	@echo ""
	@echo "Setup:"
	@echo "  make discover              - Find devices and generate config"
	@echo ""
	@echo "Device Operations:"
	@echo "  make run IP=192.168.2.x    - Compile and upload to device (OTA)"
	@echo "  make logs IP=192.168.2.x   - Stream logs from device"
	@echo "  make validate IP=192.168.2.x - Validate config for device"
	@echo "  make compile IP=192.168.2.x  - Compile without uploading"
	@echo ""
	@echo "Bulk Operations:"
	@echo "  make list                  - List all configured devices"
	@echo "  make run-all               - Run against all configured devices"
	@echo "  make run-config CONFIG=x.yaml   - Run on all devices for a config"
	@echo "  make logs-config CONFIG=x.yaml  - Stream logs from all devices for a config"
	@echo "  make validate-all          - Validate all device configs"

check-config:
	@if [ ! -f "$(CONFIG_FILE)" ]; then \
		echo "Error: $(CONFIG_FILE) not found."; \
		echo "Run 'make discover' to generate it."; \
		exit 1; \
	fi

discover:
	@chmod +x $(SCRIPTS_DIR)/discover-devices.sh
	@echo "# ESPHome Devices Configuration" > $(CONFIG_FILE).new
	@echo "# Generated on $$(date)" >> $(CONFIG_FILE).new
	@$(SCRIPTS_DIR)/discover-devices.sh >> $(CONFIG_FILE).new
	@if [ -f "$(CONFIG_FILE)" ]; then \
		echo ""; \
		echo "New config saved to $(CONFIG_FILE).new"; \
		echo "Review and run: mv $(CONFIG_FILE).new $(CONFIG_FILE)"; \
	else \
		mv $(CONFIG_FILE).new $(CONFIG_FILE); \
		echo ""; \
		echo "Created $(CONFIG_FILE)"; \
	fi
	@cat $(CONFIG_FILE).new 2>/dev/null || cat $(CONFIG_FILE)

# Lookup config file for an IP address (ignores trailing comments)
define lookup_config
$(shell awk -v ip="$(1)" ' \
	/^\[.*\]$$/ { config = substr($$0, 2, length($$0)-2) } \
	/^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/ { split($$0, a, " "); if (a[1] == ip) print config }' $(CONFIG_FILE) 2>/dev/null)
endef

list: check-config
	@echo "Configured devices:"
	@awk ' \
		/^\[.*\]$$/ { config = substr($$0, 2, length($$0)-2); printf "\n%s\n", config } \
		/^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/ { printf "  %s\n", $$0 }' $(CONFIG_FILE)
	@echo ""

run: check-config
ifndef IP
	$(error IP is required. Usage: make run IP=192.168.2.x)
endif
	$(eval CONFIG := $(call lookup_config,$(IP)))
	@if [ -z "$(CONFIG)" ]; then \
		echo "Error: IP '$(IP)' not found in $(CONFIG_FILE)"; \
		exit 1; \
	fi
	@if [ ! -f "$(CONFIG)" ]; then \
		echo "Error: Config file '$(CONFIG)' not found"; \
		exit 1; \
	fi
	@echo "Running: $(CONFIG) -> $(IP)"
	esphome run --no-logs $(CONFIG) --device $(IP)

upload: run

logs: check-config
ifndef IP
	$(error IP is required. Usage: make logs IP=192.168.2.x)
endif
	$(eval CONFIG := $(call lookup_config,$(IP)))
	@if [ -z "$(CONFIG)" ]; then \
		echo "Error: IP '$(IP)' not found"; \
		exit 1; \
	fi
	esphome logs $(CONFIG) --device $(IP)

validate: check-config
ifndef IP
	$(error IP is required. Usage: make validate IP=192.168.2.x)
endif
	$(eval CONFIG := $(call lookup_config,$(IP)))
	@if [ -z "$(CONFIG)" ]; then \
		echo "Error: IP '$(IP)' not found"; \
		exit 1; \
	fi
	esphome config $(CONFIG)

compile: check-config
ifndef IP
	$(error IP is required. Usage: make compile IP=192.168.2.x)
endif
	$(eval CONFIG := $(call lookup_config,$(IP)))
	@if [ -z "$(CONFIG)" ]; then \
		echo "Error: IP '$(IP)' not found"; \
		exit 1; \
	fi
	esphome compile $(CONFIG)

run-all: check-config
	@set -eo pipefail; \
	awk ' \
		/^\[.*\]$$/ { config = substr($$0, 2, length($$0)-2) } \
		/^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/ { print config ":" $$1 }' $(CONFIG_FILE) | \
	while IFS=: read -r config ip; do \
		echo "=== $$config -> $$ip ==="; \
		esphome run --no-logs "$$config" --device "$$ip"; \
		echo ""; \
	done

# Lookup all IPs for a config file
define lookup_ips
$(shell awk -v cfg="$(1)" ' \
	/^\[.*\]$$/ { in_section = (substr($$0, 2, length($$0)-2) == cfg) } \
	in_section && /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/ { split($$0, a, " "); print a[1] }' $(CONFIG_FILE) 2>/dev/null)
endef

run-config: check-config
ifndef CONFIG
	$(error CONFIG is required. Usage: make run-config CONFIG=shelly-1-mini-gen3.yaml)
endif
	@if [ ! -f "$(CONFIG)" ]; then \
		echo "Error: Config file '$(CONFIG)' not found"; \
		exit 1; \
	fi
	$(eval IPS := $(call lookup_ips,$(CONFIG)))
	@set -e; \
	if [ -z "$(IPS)" ]; then \
		echo "No devices found for '$(CONFIG)' in $(CONFIG_FILE)"; \
		echo "Running with mDNS discovery..."; \
		esphome run --no-logs $(CONFIG); \
	else \
		echo "Found devices for $(CONFIG): $(IPS)"; \
		for ip in $(IPS); do \
			echo ""; \
			echo "=== $(CONFIG) -> $$ip ==="; \
			esphome run --no-logs $(CONFIG) --device $$ip; \
		done; \
		echo ""; \
		echo "All devices updated!"; \
	fi

logs-config: check-config
ifndef CONFIG
	$(error CONFIG is required. Usage: make logs-config CONFIG=shelly-1-mini-gen3.yaml)
endif
	@if [ ! -f "$(CONFIG)" ]; then \
		echo "Error: Config file '$(CONFIG)' not found"; \
		exit 1; \
	fi
	$(eval IPS := $(call lookup_ips,$(CONFIG)))
	@if [ -z "$(IPS)" ]; then \
		echo "No devices found for '$(CONFIG)' in $(CONFIG_FILE)"; \
		esphome logs $(CONFIG); \
	else \
		echo "Streaming logs from: $(IPS)"; \
		echo "(Press Ctrl+C to stop)"; \
		for ip in $(IPS); do \
			esphome logs $(CONFIG) --device $$ip 2>&1 | sed "s/^/[$$ip] /" & \
		done; \
		wait; \
	fi

validate-all: check-config
	@awk '/^\[.*\]$$/ { print substr($$0, 2, length($$0)-2) }' $(CONFIG_FILE) | sort -u | \
	while read -r config; do \
		echo "=== Validating $$config ==="; \
		esphome config "$$config" > /dev/null && echo "OK" || echo "FAILED"; \
	done

clean:
	rm -rf .esphome/
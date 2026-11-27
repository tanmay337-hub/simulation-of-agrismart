"""
ESP32 Node Simulation - Sector 1
Virtual Smart Agriculture Irrigation System

Runs as an independent OS process representing Farm Sector 1.
Initial state (from config/settings.json): moisture 22%, temp 29C, humidity 48%.
"""

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from esp32_nodes.base_node import run_esp32_node

SECTOR_ID = 1

if __name__ == "__main__":
    run_esp32_node(SECTOR_ID)

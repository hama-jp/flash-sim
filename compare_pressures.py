#!/usr/bin/env python3
import numpy as np
import matplotlib.pyplot as plt
from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class WaterProperties:
    P_inlet: float
    h_water_inlet: float
    T_inlet: float = 190 + 273.15
    P_outlet: float = 101325
    rho_water: float = 876.0
    h_sat_liquid: float = 419e3
    h_fg: float = 2257e3
    critical_pressure_ratio: float = 0.577

@dataclass
class RoomGeometry:
    volume: float = 400.0  # 10m x 10m x 4m

def calculate_flash_fraction(props: WaterProperties) -> float:
    x = (props.h_water_inlet - props.h_sat_liquid) / props.h_fg
    return max(0, min(1, x))

def calculate_leak_flow_rate(leak_area: float, props: WaterProperties, Cd: float = 0.62):
    P1 = props.P_inlet
    P2 = props.P_outlet
    rho = props.rho_water
    if P2 / P1 < props.critical_pressure_ratio:
        delta_P = P1 - (P1 * props.critical_pressure_ratio)
    else:
        delta_P = P1 - P2
    velocity = Cd * np.sqrt(2 * delta_P / rho)
    mass_flow = rho * leak_area * velocity
    steam_flow = mass_flow * calculate_flash_fraction(props)
    return steam_flow

def simulate_evacuation_time(steam_flow: float, room: RoomGeometry):
    duration = 200.0
    dt = 0.1
    m_air = 1.2 * room.volume
    cp_air = 1005
    T_steam = 373.15
    T_room = 298.15
    steam_mass = 0.0
    vent_rate = 0.5 / 3600

    t_50c = float('inf')
    t_vis3m = float('inf')

    for t in np.arange(0, duration, dt):
        steam_mass += (steam_flow - steam_mass * vent_rate) * dt
        # Simplified heat balance from original script
        Q_in = steam_flow * cp_air * (T_steam - T_room) * dt
        Q_out = vent_rate * m_air * cp_air * (T_room - 298.15) * dt
        T_room += (Q_in - Q_out) / (m_air * cp_air)

        if t_50c == float('inf') and (T_room - 273.15) >= 50:
            t_50c = t

        steam_conc = steam_mass / room.volume
        if t_vis3m == float('inf') and steam_conc > 0.0001:
            vis = 0.15 / steam_conc
            if vis <= 3.0:
                t_vis3m = t

        if t_50c != float('inf') and t_vis3m != float('inf'):
            break

    return min(t_50c, t_vis3m)

def main():
    valve_full_area = np.pi * (0.6 / 2)**2
    leak_ratios = [0.0001, 0.001, 0.005, 0.01, 0.02, 0.05]
    leak_labels = ["0.01%", "0.1%", "0.5%", "1%", "2%", "5%"]

    # 1.5 MPa
    props15 = WaterProperties(P_inlet=1.5e6, h_water_inlet=807e3)
    # 10.0 MPa
    props100 = WaterProperties(P_inlet=10.0e6, h_water_inlet=815e3)

    room = RoomGeometry()

    times15 = []
    times100 = []

    for r in leak_ratios:
        area = valve_full_area * r
        times15.append(simulate_evacuation_time(calculate_leak_flow_rate(area, props15), room))
        times100.append(simulate_evacuation_time(calculate_leak_flow_rate(area, props100), room))

    plt.figure(figsize=(12, 7))
    x = np.arange(len(leak_labels))
    width = 0.35

    plt.bar(x - width/2, times15, width, label='1.5 MPa', color='skyblue')
    plt.bar(x + width/2, times100, width, label='10.0 MPa', color='salmon')

    plt.axhline(y=19.1, color='red', linestyle='--', label='Required Escape Time (19.1s)')

    plt.xticks(x, leak_labels)
    plt.ylabel('Available Evacuation Time [s]')
    plt.xlabel('Leak Area (% of Seat Area)')
    plt.title('Comparison of Available Evacuation Time: 1.5 MPa vs 10.0 MPa\n(Min of Visibility < 3m or Temp > 50°C)')
    plt.legend()
    plt.grid(True, alpha=0.3, axis='y')
    plt.yscale('log')
    plt.ylim(0.1, 300)

    for i, v in enumerate(times15):
        if v < float('inf'):
            plt.text(i - width/2, v, f'{v:.1f}s', ha='center', va='bottom', fontsize=9)
        else:
            plt.text(i - width/2, 200, '>200s', ha='center', va='bottom', fontsize=9)

    for i, v in enumerate(times100):
        if v < float('inf'):
            plt.text(i + width/2, v, f'{v:.1f}s', ha='center', va='bottom', fontsize=9)
        else:
            plt.text(i + width/2, 200, '>200s', ha='center', va='bottom', fontsize=9)

    plt.tight_layout()
    plt.savefig('pressure_comparison.png', dpi=150)
    print("Graph saved to 'pressure_comparison.png'")

if __name__ == "__main__":
    main()

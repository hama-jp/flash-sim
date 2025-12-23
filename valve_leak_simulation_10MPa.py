#!/usr/bin/env python3
"""
Gate Valve Seat Leak Impact Simulation - 10 MPa Case

Conditions: 600A gate valve, inlet 10MPa/190C hot water, outlet atmospheric (15mx15m room)
Purpose: Quantify risk of single-valve isolation work
"""

import numpy as np
import matplotlib.pyplot as plt
from dataclasses import dataclass
from typing import List, Tuple
import warnings
warnings.filterwarnings('ignore')


# =============================================================================
# Physical Constants and Water Properties
# =============================================================================

@dataclass
class WaterProperties:
    """Water/Steam thermodynamic properties"""
    # Inlet: 10 MPa, 190C
    P_inlet: float = 10.0e6     # Pa (10 MPa)
    T_inlet: float = 190 + 273.15  # K (190C)

    # Outlet: Atmospheric
    P_outlet: float = 101325    # Pa (1 atm)
    T_outlet: float = 100 + 273.15  # K (100C saturation)

    # At 10 MPa, saturation temp is ~311C
    # 190C < 311C, so this is subcooled water
    # But flash evaporation occurs on atmospheric release

    # Water properties (~190C)
    rho_water: float = 876.0    # kg/m³
    cp_water: float = 4410.0    # J/(kg·K)
    h_water_inlet: float = 815e3  # J/kg (enthalpy @10MPa, 190C - slightly higher due to pressure)

    # Atmospheric saturation properties
    h_sat_liquid: float = 419e3   # J/kg
    h_sat_vapor: float = 2676e3   # J/kg
    h_fg: float = 2257e3          # J/kg (latent heat)

    rho_steam: float = 0.598     # kg/m³

    # Critical pressure ratio (water)
    critical_pressure_ratio: float = 0.577


@dataclass
class RoomGeometry:
    """Room dimensions"""
    length: float = 15.0    # m
    width: float = 15.0     # m
    height: float = 4.0     # m

    @property
    def volume(self) -> float:
        return self.length * self.width * self.height

    @property
    def floor_area(self) -> float:
        return self.length * self.width


@dataclass
class ValveSpec:
    """600A Gate Valve Specification"""
    nominal_diameter: float = 0.600  # m (600A = 600mm)

    @property
    def full_area(self) -> float:
        return np.pi * (self.nominal_diameter / 2) ** 2


# =============================================================================
# Leak Cases
# =============================================================================

def get_leak_cases(valve: ValveSpec) -> List[Tuple[str, float]]:
    """Define realistic seat leak area cases"""
    full_area = valve.full_area

    cases = [
        ("Micro (0.01%)", full_area * 0.0001),
        ("Small (0.1%)", full_area * 0.001),
        ("Medium (0.5%)", full_area * 0.005),
        ("Large (1%)", full_area * 0.01),
        ("Critical (2%)", full_area * 0.02),
        ("Catastrophic (5%)", full_area * 0.05),
    ]

    return cases


# =============================================================================
# Flash Evaporation Calculation
# =============================================================================

def calculate_flash_fraction(props: WaterProperties) -> float:
    """Calculate flash evaporation fraction"""
    x = (props.h_water_inlet - props.h_sat_liquid) / props.h_fg
    return max(0, min(1, x))


def calculate_leak_flow_rate(
    leak_area: float,
    props: WaterProperties,
    Cd: float = 0.62
) -> Tuple[float, float, float]:
    """
    Calculate leak flow rate considering critical (choked) flow

    At high pressure ratios (10MPa to 0.1MPa), flow is definitely choked
    """
    P1 = props.P_inlet
    P2 = props.P_outlet
    rho = props.rho_water

    pressure_ratio = P2 / P1  # ~0.01 for 10MPa case

    if pressure_ratio < props.critical_pressure_ratio:
        # Critical (choked) flow - always the case for 10MPa
        P_crit = P1 * props.critical_pressure_ratio
        delta_P = P1 - P_crit
    else:
        delta_P = P1 - P2

    velocity = Cd * np.sqrt(2 * delta_P / rho)
    mass_flow = rho * leak_area * velocity

    flash_fraction = calculate_flash_fraction(props)
    steam_flow = mass_flow * flash_fraction

    return mass_flow, velocity, steam_flow


# =============================================================================
# Room Steam Diffusion Model
# =============================================================================

def simulate_room_conditions(
    steam_flow: float,
    room: RoomGeometry,
    duration: float = 60.0,
    dt: float = 0.1,
    ventilation_rate: float = 0.5
) -> dict:
    """Calculate room steam concentration and temperature over time"""

    T_room_init = 25 + 273.15
    rho_air = 1.2
    cp_air = 1005

    m_air = rho_air * room.volume
    T_steam = 100 + 273.15

    t_array = np.arange(0, duration + dt, dt)
    n_steps = len(t_array)

    T_room = np.zeros(n_steps)
    steam_mass = np.zeros(n_steps)
    visibility = np.zeros(n_steps)
    humidity = np.zeros(n_steps)

    T_room[0] = T_room_init
    visibility[0] = 50.0

    vent_rate = ventilation_rate / 3600

    for i in range(1, n_steps):
        dm_steam = steam_flow * dt
        dm_out = steam_mass[i-1] * vent_rate * dt
        steam_mass[i] = steam_mass[i-1] + dm_steam - dm_out

        Q_in = steam_flow * cp_air * (T_steam - T_room[i-1]) * dt
        Q_out = vent_rate * m_air * cp_air * (T_room[i-1] - T_room_init) * dt

        dT = (Q_in - Q_out) / (m_air * cp_air)
        T_room[i] = T_room[i-1] + dT

        steam_concentration = steam_mass[i] / room.volume

        if steam_concentration > 0.0001:
            visibility[i] = min(50, 0.15 / steam_concentration)
        else:
            visibility[i] = 50

        P_sat = 610.78 * np.exp(17.27 * (T_room[i] - 273.15) / (T_room[i] - 35.85))
        P_steam = steam_concentration * 461.5 * T_room[i]
        humidity[i] = min(100, P_steam / P_sat * 100)

    return {
        'time': t_array,
        'temperature': T_room - 273.15,
        'steam_mass': steam_mass,
        'visibility': visibility,
        'humidity': humidity,
        'steam_concentration': steam_mass / room.volume
    }


# =============================================================================
# Risk Assessment
# =============================================================================

@dataclass
class RiskAssessment:
    """Risk assessment results"""
    case_name: str
    leak_area: float
    leak_area_mm2: float
    mass_flow: float
    steam_flow: float
    jet_velocity: float
    flash_fraction: float
    time_to_50C: float
    time_to_visibility_3m: float
    time_to_humidity_100: float
    burn_risk_distance: float


def assess_risk(
    case_name: str,
    leak_area: float,
    props: WaterProperties,
    room: RoomGeometry
) -> RiskAssessment:
    """Perform risk assessment"""

    mass_flow, velocity, steam_flow = calculate_leak_flow_rate(leak_area, props)
    flash_fraction = calculate_flash_fraction(props)

    results = simulate_room_conditions(steam_flow, room, duration=120)

    def find_threshold_time(data, threshold, comparison='>='):
        if comparison == '>=':
            idx = np.where(data >= threshold)[0]
        else:
            idx = np.where(data <= threshold)[0]
        return results['time'][idx[0]] if len(idx) > 0 else float('inf')

    time_to_50C = find_threshold_time(results['temperature'], 50)
    time_to_visibility_3m = find_threshold_time(results['visibility'], 3, '<=')
    time_to_humidity_100 = find_threshold_time(results['humidity'], 99)

    if steam_flow > 0.01:
        jet_diameter = np.sqrt(4 * leak_area / np.pi)
        burn_risk_distance = min(10, 20 * jet_diameter * (velocity / 100))
    else:
        burn_risk_distance = 0.5

    return RiskAssessment(
        case_name=case_name,
        leak_area=leak_area,
        leak_area_mm2=leak_area * 1e6,
        mass_flow=mass_flow,
        steam_flow=steam_flow,
        jet_velocity=velocity,
        flash_fraction=flash_fraction,
        time_to_50C=time_to_50C,
        time_to_visibility_3m=time_to_visibility_3m,
        time_to_humidity_100=time_to_humidity_100,
        burn_risk_distance=burn_risk_distance
    )


# =============================================================================
# Output and Visualization
# =============================================================================

def print_summary_table(assessments: List[RiskAssessment], pressure_mpa: float):
    """Print results summary table"""

    print("\n" + "=" * 100)
    print(f"Seat Leak Impact Assessment Summary - {pressure_mpa} MPa Case")
    print(f"Conditions: 600A Gate Valve, Inlet {pressure_mpa}MPa/190C, Room 15m x 15m x 4m")
    print("=" * 100)

    print(f"\nFlash evaporation rate: {assessments[0].flash_fraction * 100:.1f}%")

    print(f"\n{'Case':<20} {'Leak Area':>12} {'Flow':>10} {'Steam':>10} "
          f"{'Velocity':>10} {'50C Time':>10} {'Vis 3m':>10} {'Burn Dist':>10}")
    print(f"{'':<20} {'[mm2]':>12} {'[kg/s]':>10} {'[kg/s]':>10} "
          f"{'[m/s]':>10} {'[sec]':>10} {'[sec]':>10} {'[m]':>10}")
    print("-" * 100)

    for a in assessments:
        t50 = f"{a.time_to_50C:.1f}" if a.time_to_50C < float('inf') else ">120"
        tvis = f"{a.time_to_visibility_3m:.1f}" if a.time_to_visibility_3m < float('inf') else ">120"

        print(f"{a.case_name:<20} {a.leak_area_mm2:>12.1f} {a.mass_flow:>10.2f} "
              f"{a.steam_flow:>10.2f} {a.jet_velocity:>10.1f} "
              f"{t50:>10} {tvis:>10} {a.burn_risk_distance:>10.1f}")

    print("=" * 100)

    # Warnings
    print("\n[Key Findings]")
    print("-" * 60)

    critical_cases = [a for a in assessments if a.time_to_visibility_3m < 10]
    if critical_cases:
        print("WARNING: Visibility drops to <3m within 10 seconds:")
        for a in critical_cases:
            print(f"   - {a.case_name}: {a.time_to_visibility_3m:.1f}s to visibility <3m")

    fast_heating = [a for a in assessments if a.time_to_50C < 30]
    if fast_heating:
        print("\nWARNING: Room temperature exceeds 50C within 30 seconds:")
        for a in fast_heating:
            print(f"   - {a.case_name}: {a.time_to_50C:.1f}s to reach 50C")

    high_flow = [a for a in assessments if a.mass_flow > 10]
    if high_flow:
        print("\nWARNING: High volume hot water/steam release:")
        for a in high_flow:
            print(f"   - {a.case_name}: {a.mass_flow:.1f} kg/s ({a.mass_flow * 60:.0f} kg/min)")


def create_visualizations(assessments: List[RiskAssessment], room: RoomGeometry,
                         props: WaterProperties, pressure_mpa: float):
    """Create result visualizations"""

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    colors = plt.cm.Reds(np.linspace(0.3, 0.9, len(assessments)))

    # 1. Room Temperature Rise
    ax1 = axes[0, 0]
    for i, a in enumerate(assessments):
        _, _, steam_flow = calculate_leak_flow_rate(a.leak_area, props)
        results = simulate_room_conditions(steam_flow, room, duration=60)
        ax1.plot(results['time'], results['temperature'],
                label=a.case_name, color=colors[i], linewidth=2)

    ax1.axhline(y=50, color='orange', linestyle='--', label='50C (Discomfort)')
    ax1.axhline(y=70, color='red', linestyle='--', label='70C (Burn risk)')
    ax1.set_xlabel('Time [s]')
    ax1.set_ylabel('Room Temperature [C]')
    ax1.set_title(f'Room Temperature Rise ({pressure_mpa} MPa)')
    ax1.legend(loc='upper left', fontsize=8)
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim(0, 60)

    # 2. Visibility Degradation
    ax2 = axes[0, 1]
    for i, a in enumerate(assessments):
        _, _, steam_flow = calculate_leak_flow_rate(a.leak_area, props)
        results = simulate_room_conditions(steam_flow, room, duration=60)
        ax2.plot(results['time'], results['visibility'],
                label=a.case_name, color=colors[i], linewidth=2)

    ax2.axhline(y=3, color='orange', linestyle='--', label='3m (Escape difficulty)')
    ax2.axhline(y=1, color='red', linestyle='--', label='1m (Almost zero visibility)')
    ax2.set_xlabel('Time [s]')
    ax2.set_ylabel('Visibility [m]')
    ax2.set_title(f'Visibility Degradation ({pressure_mpa} MPa)')
    ax2.legend(loc='upper right', fontsize=8)
    ax2.grid(True, alpha=0.3)
    ax2.set_xlim(0, 60)
    ax2.set_ylim(0, 20)

    # 3. Evacuation Time
    ax3 = axes[1, 0]
    evac_times = [min(a.time_to_visibility_3m, a.time_to_50C) for a in assessments]

    bars = ax3.bar(range(len(assessments)), evac_times, color=colors)
    ax3.set_xticks(range(len(assessments)))
    ax3.set_xticklabels([a.case_name.split('(')[0].strip() for a in assessments],
                        rotation=45, ha='right', fontsize=9)
    ax3.set_ylabel('Available Evacuation Time [s]')
    ax3.set_title(f'Time Available for Evacuation ({pressure_mpa} MPa)')
    ax3.axhline(y=10, color='red', linestyle='--', linewidth=2, label='10s (Minimum escape time)')
    ax3.axhline(y=30, color='orange', linestyle='--', linewidth=2, label='30s (Marginal)')
    ax3.legend()
    ax3.grid(True, alpha=0.3, axis='y')

    for bar, val in zip(bars, evac_times):
        if val < float('inf'):
            ax3.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                    f'{val:.1f}s', ha='center', va='bottom', fontsize=9)

    # 4. Flow Rate
    ax4 = axes[1, 1]
    x = np.arange(len(assessments))
    width = 0.35

    mass_flows = [a.mass_flow for a in assessments]
    steam_flows = [a.steam_flow for a in assessments]

    ax4.bar(x - width/2, mass_flows, width, label='Total mass flow', color='steelblue')
    ax4.bar(x + width/2, steam_flows, width, label='Steam generation', color='orangered')

    ax4.set_xticks(x)
    ax4.set_xticklabels([a.case_name.split('(')[0].strip() for a in assessments],
                        rotation=45, ha='right', fontsize=9)
    ax4.set_ylabel('Flow Rate [kg/s]')
    ax4.set_title(f'Leak Flow Rate ({pressure_mpa} MPa)')
    ax4.legend()
    ax4.grid(True, alpha=0.3, axis='y')
    ax4.set_yscale('log')

    plt.tight_layout()
    plt.savefig(f'valve_leak_analysis_{pressure_mpa}MPa.png', dpi=150, bbox_inches='tight')
    print(f"\nGraph saved to 'valve_leak_analysis_{pressure_mpa}MPa.png'")

    return fig


def create_evacuation_analysis(assessments: List[RiskAssessment]):
    """Detailed evacuation time analysis"""

    print("\n" + "=" * 80)
    print("Evacuation Time Analysis")
    print("=" * 80)

    reaction_time = 2.0
    decision_time = 3.0
    movement_speed = 1.0
    max_escape_distance = 15 * np.sqrt(2)

    min_escape_time = reaction_time + decision_time + max_escape_distance / movement_speed

    print(f"\nEvacuation Scenario Assumptions:")
    print(f"  - Reaction time: {reaction_time}s")
    print(f"  - Decision time: {decision_time}s")
    print(f"  - Movement speed: {movement_speed} m/s (impaired visibility)")
    print(f"  - Max escape distance: {max_escape_distance:.1f}m (room diagonal)")
    print(f"  - Minimum required time: {min_escape_time:.1f}s")

    print(f"\n{'Case':<25} {'Available':>12} {'Required':>10} {'Assessment':>20}")
    print("-" * 70)

    for a in assessments:
        available = min(a.time_to_visibility_3m, a.time_to_50C)
        if available >= min_escape_time * 1.5:
            status = "Evacuation possible"
        elif available >= min_escape_time:
            status = "Evacuation difficult"
        elif available >= reaction_time + decision_time:
            status = "Evacuation very difficult"
        else:
            status = "Evacuation impossible"

        avail_str = f"{available:.1f}s" if available < float('inf') else ">120s"
        print(f"{a.case_name:<25} {avail_str:>12} {min_escape_time:>10.1f}s {status:>20}")

    print("\n" + "=" * 80)
    print("[CONCLUSION]")
    print("-" * 80)

    dangerous_cases = [a for a in assessments
                       if min(a.time_to_visibility_3m, a.time_to_50C) < min_escape_time]

    if dangerous_cases:
        print(f"For seat leak area >= {dangerous_cases[0].leak_area_mm2:.0f} mm2,")
        print(f"safe worker evacuation is extremely difficult.")
        print(f"\nSingle-valve isolation work poses HIGH RISK of severe burns.")
        print(f"Double block and bleed procedures are MANDATORY.")


# =============================================================================
# Main
# =============================================================================

def main():
    """Main execution"""

    pressure_mpa = 10.0

    print("\n" + "#" * 80)
    print(f"#  Gate Valve Seat Leak Simulation - {pressure_mpa} MPa Case")
    print("#" * 80)

    props = WaterProperties()
    room = RoomGeometry()
    valve = ValveSpec()

    print(f"\n[Configuration]")
    print(f"  Valve: {int(valve.nominal_diameter * 1000)}A Gate Valve")
    print(f"  Full seat area: {valve.full_area * 1e6:.0f} mm2 ({valve.full_area:.4f} m2)")
    print(f"  Inlet: {props.P_inlet/1e6:.1f} MPa, {props.T_inlet - 273.15:.0f}C")
    print(f"  Outlet: Atmospheric ({props.P_outlet/1e3:.0f} kPa)")
    print(f"  Room: {room.length}m x {room.width}m x {room.height}m = {room.volume:.0f} m3")

    cases = get_leak_cases(valve)

    assessments = []
    for case_name, leak_area in cases:
        assessment = assess_risk(case_name, leak_area, props, room)
        assessments.append(assessment)

    print_summary_table(assessments, pressure_mpa)
    create_evacuation_analysis(assessments)

    try:
        create_visualizations(assessments, room, props, pressure_mpa)
    except Exception as e:
        print(f"\nNote: Graph generation error: {e}")

    # Summary
    print("\n" + "#" * 80)
    print("#  SIMULATION SUMMARY")
    print("#" * 80)
    print(f"""
This simulation uses simplified models for estimation. Actual conditions
may vary based on site factors (ventilation, obstacles, valve location).

However, the order of magnitude is clear:

1. At {pressure_mpa} MPa, even 0.1% seat leak results in ~{assessments[1].mass_flow:.0f} kg/s
   hot water release with significant steam generation

2. At 0.5%+ leak area, visibility drops to <3m within {assessments[2].time_to_visibility_3m:.0f} seconds,
   making safe evacuation practically impossible

3. Workers near the valve (<1m) face immediate severe burn risk
   with no time to react

[RECOMMENDED SAFETY MEASURES]
- PROHIBIT single-valve isolation for opening work
- STANDARDIZE double block and bleed procedures
- Maintain safe distance during valve operations
- Regular seat leak testing
""")

    return assessments


if __name__ == "__main__":
    assessments = main()

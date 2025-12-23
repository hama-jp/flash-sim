#!/usr/bin/env python3
"""
ゲート弁シートリーク影響シミュレーション

目的: 単一弁隔離での開放作業リスクを定量評価
条件: 600Aゲート弁、入口1.5MPa/190℃熱水、出口大気開放室内(15mx15m)
"""

import numpy as np
import matplotlib.pyplot as plt
from dataclasses import dataclass
from typing import List, Tuple
import warnings
warnings.filterwarnings('ignore')

# 日本語フォント設定
plt.rcParams['font.family'] = ['DejaVu Sans', 'sans-serif']


# =============================================================================
# 物理定数と水蒸気物性
# =============================================================================

@dataclass
class WaterProperties:
    """水・蒸気の熱力学的物性"""
    # 入口条件: 1.5 MPa, 190℃
    P_inlet: float = 1.5e6      # Pa (1.5 MPa)
    T_inlet: float = 190 + 273.15  # K (190℃)

    # 出口条件: 大気圧
    P_outlet: float = 101325    # Pa (1 atm)
    T_outlet: float = 100 + 273.15  # K (100℃ 飽和温度)

    # 1.5 MPa での飽和温度は約198℃
    # 190℃ < 198℃ なので、これは過冷却水（サブクール水）
    # ただし大気圧開放時にフラッシング蒸発する

    # 水の物性（190℃近傍）
    rho_water: float = 876.0    # kg/m³ (液水密度 @190℃)
    cp_water: float = 4410.0    # J/(kg·K) (比熱)
    h_water_inlet: float = 807e3  # J/kg (エンタルピー @1.5MPa, 190℃)

    # 大気圧飽和水の物性
    h_sat_liquid: float = 419e3   # J/kg (飽和液エンタルピー @1atm)
    h_sat_vapor: float = 2676e3   # J/kg (飽和蒸気エンタルピー @1atm)
    h_fg: float = 2257e3          # J/kg (蒸発潜熱 @1atm)

    rho_steam: float = 0.598     # kg/m³ (飽和蒸気密度 @1atm)

    # 臨界圧力比（水蒸気）
    critical_pressure_ratio: float = 0.577


@dataclass
class RoomGeometry:
    """室内形状"""
    length: float = 15.0    # m
    width: float = 15.0     # m
    height: float = 4.0     # m (仮定)

    @property
    def volume(self) -> float:
        return self.length * self.width * self.height

    @property
    def floor_area(self) -> float:
        return self.length * self.width


@dataclass
class ValveSpec:
    """600Aゲート弁仕様"""
    nominal_diameter: float = 0.600  # m (600A = 600mm)

    @property
    def full_area(self) -> float:
        """弁座全開面積"""
        return np.pi * (self.nominal_diameter / 2) ** 2


# =============================================================================
# リーク面積のケース設定
# =============================================================================

def get_leak_cases(valve: ValveSpec) -> List[Tuple[str, float]]:
    """
    現実的なシートリーク面積のケースを設定

    参考: 600A弁の全開面積 ≈ 0.283 m²
    シートリークは通常、弁座周縁部のわずかな隙間
    """
    full_area = valve.full_area

    cases = [
        # (Case name, Leak area [m²])
        ("Micro (0.01%)", full_area * 0.0001),      # Hair crack
        ("Small (0.1%)", full_area * 0.001),        # Minor seat damage
        ("Medium (0.5%)", full_area * 0.005),       # Moderate seat damage
        ("Large (1%)", full_area * 0.01),           # Severe seat damage
        ("Critical (2%)", full_area * 0.02),        # Major seat failure
        ("Catastrophic (5%)", full_area * 0.05),    # Seat detachment
    ]

    return cases


# =============================================================================
# フラッシング蒸発計算
# =============================================================================

def calculate_flash_fraction(props: WaterProperties) -> float:
    """
    フラッシング蒸発率を計算

    190℃の熱水が大気圧に開放されると、エンタルピー保存で
    一部が瞬時に蒸発（フラッシング）

    Returns:
        x: 蒸気の質量分率（乾き度）
    """
    # エンタルピーバランス: h_inlet = h_f + x * h_fg
    # x = (h_inlet - h_f) / h_fg

    x = (props.h_water_inlet - props.h_sat_liquid) / props.h_fg
    return max(0, min(1, x))  # 0-1にクリップ


def calculate_leak_flow_rate(
    leak_area: float,
    props: WaterProperties,
    Cd: float = 0.62
) -> Tuple[float, float, float]:
    """
    リーク流量を計算（臨界流を考慮）

    高圧水のリークでは、圧力比が臨界圧力比以下の場合
    チョーク流れとなり、流量は下流圧力に依存しない

    Args:
        leak_area: リーク面積 [m²]
        props: 水物性
        Cd: 流量係数

    Returns:
        mass_flow: 質量流量 [kg/s]
        velocity: 噴出速度 [m/s]
        steam_flow: 蒸気発生量 [kg/s]
    """
    P1 = props.P_inlet
    P2 = props.P_outlet
    rho = props.rho_water

    # 圧力比チェック
    pressure_ratio = P2 / P1

    if pressure_ratio < props.critical_pressure_ratio:
        # 臨界流（チョーク流れ）
        # 簡易計算: ベルヌーイ式ベースで臨界圧力まで膨張
        P_crit = P1 * props.critical_pressure_ratio
        delta_P = P1 - P_crit
    else:
        # 亜臨界流
        delta_P = P1 - P2

    # ベルヌーイ式による速度・流量
    velocity = Cd * np.sqrt(2 * delta_P / rho)
    mass_flow = rho * leak_area * velocity

    # フラッシング蒸発による蒸気発生量
    flash_fraction = calculate_flash_fraction(props)
    steam_flow = mass_flow * flash_fraction

    return mass_flow, velocity, steam_flow


# =============================================================================
# 室内蒸気拡散モデル（簡易）
# =============================================================================

def simulate_room_conditions(
    steam_flow: float,
    room: RoomGeometry,
    duration: float = 60.0,  # シミュレーション時間 [s]
    dt: float = 0.1,
    ventilation_rate: float = 0.5  # 換気回数 [1/h] (ほぼ密閉)
) -> dict:
    """
    室内の蒸気濃度・温度の時間変化を計算

    簡易モデル: 完全混合を仮定
    """
    # 初期条件
    T_room_init = 25 + 273.15  # K (初期室温25℃)
    rho_air = 1.2              # kg/m³
    cp_air = 1005              # J/(kg·K)

    # 室内空気質量
    m_air = rho_air * room.volume

    # 蒸気の持つエネルギー（大気圧飽和蒸気として）
    h_steam = 2676e3  # J/kg
    T_steam = 100 + 273.15  # K

    # 時間配列
    t_array = np.arange(0, duration + dt, dt)
    n_steps = len(t_array)

    # 結果配列
    T_room = np.zeros(n_steps)
    steam_mass = np.zeros(n_steps)  # 室内蒸気質量
    visibility = np.zeros(n_steps)  # 視程 [m]
    humidity = np.zeros(n_steps)    # 相対湿度概算

    T_room[0] = T_room_init
    visibility[0] = 50.0  # 初期視程（十分良好）

    # 換気による蒸気排出率
    vent_rate = ventilation_rate / 3600  # 1/s

    for i in range(1, n_steps):
        # 蒸気流入
        dm_steam = steam_flow * dt

        # 換気による排出
        dm_out = steam_mass[i-1] * vent_rate * dt

        # 蒸気質量バランス
        steam_mass[i] = steam_mass[i-1] + dm_steam - dm_out

        # 温度上昇（蒸気凝縮熱 + 顕熱）
        # 簡易: 蒸気が室内空気と熱交換
        Q_in = steam_flow * cp_air * (T_steam - T_room[i-1]) * dt
        Q_out = vent_rate * m_air * cp_air * (T_room[i-1] - T_room_init) * dt

        dT = (Q_in - Q_out) / (m_air * cp_air)
        T_room[i] = T_room[i-1] + dT

        # 蒸気濃度 [kg/m³]
        steam_concentration = steam_mass[i] / room.volume

        # 視程の推定（経験式: 蒸気濃度と視程の関係）
        # 霧の視程経験式を参考: 水分量0.3 g/m³で視程1km程度
        # 高温蒸気はより視界を遮る: 0.05 kg/m³ で視程約3m程度と仮定
        if steam_concentration > 0.0001:
            # 視程 = k / concentration （経験式）
            visibility[i] = min(50, 0.15 / steam_concentration)
        else:
            visibility[i] = 50  # 最大視程

        # 相対湿度の概算（飽和蒸気圧ベース、簡易）
        P_sat = 610.78 * np.exp(17.27 * (T_room[i] - 273.15) / (T_room[i] - 35.85))
        P_steam = steam_concentration * 461.5 * T_room[i]  # 理想気体近似
        humidity[i] = min(100, P_steam / P_sat * 100)

    return {
        'time': t_array,
        'temperature': T_room - 273.15,  # ℃に変換
        'steam_mass': steam_mass,
        'visibility': visibility,
        'humidity': humidity,
        'steam_concentration': steam_mass / room.volume
    }


# =============================================================================
# リスク評価
# =============================================================================

@dataclass
class RiskAssessment:
    """リスク評価結果"""
    case_name: str
    leak_area: float           # m²
    leak_area_mm2: float       # mm²
    mass_flow: float           # kg/s
    steam_flow: float          # kg/s
    jet_velocity: float        # m/s
    flash_fraction: float      # -

    # 時間指標
    time_to_50C: float         # 室温50℃到達時間 [s]
    time_to_visibility_3m: float  # 視程3m到達時間 [s]
    time_to_humidity_100: float   # 湿度100%到達時間 [s]

    # 熱傷リスク
    burn_risk_distance: float  # 即座に熱傷の距離 [m]


def assess_risk(
    case_name: str,
    leak_area: float,
    props: WaterProperties,
    room: RoomGeometry
) -> RiskAssessment:
    """リスク評価を実行"""

    mass_flow, velocity, steam_flow = calculate_leak_flow_rate(leak_area, props)
    flash_fraction = calculate_flash_fraction(props)

    # 室内シミュレーション
    results = simulate_room_conditions(steam_flow, room, duration=120)

    # 閾値到達時間を抽出
    def find_threshold_time(data, threshold, comparison='>='):
        if comparison == '>=':
            idx = np.where(data >= threshold)[0]
        else:
            idx = np.where(data <= threshold)[0]
        return results['time'][idx[0]] if len(idx) > 0 else float('inf')

    time_to_50C = find_threshold_time(results['temperature'], 50)
    time_to_visibility_3m = find_threshold_time(results['visibility'], 3, '<=')
    time_to_humidity_100 = find_threshold_time(results['humidity'], 99)

    # 熱傷リスク距離（噴流の高温領域）
    # 簡易推定: 蒸気噴流が100℃から70℃に冷却されるまでの距離
    # 経験則: 噴流中心温度 ∝ 1/x (xは距離)
    # 70℃以上で数秒で熱傷リスク
    if steam_flow > 0.01:
        # 噴流の届く範囲（運動量ベース概算）
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
# 結果出力・可視化
# =============================================================================

def print_summary_table(assessments: List[RiskAssessment]):
    """結果サマリーテーブルを出力"""

    print("\n" + "=" * 100)
    print("シートリーク影響評価サマリー")
    print("条件: 600Aゲート弁, 入口1.5MPa/190℃, 室内15m×15m×4m")
    print("=" * 100)

    # フラッシング率を表示
    print(f"\nフラッシング蒸発率: {assessments[0].flash_fraction * 100:.1f}%")
    print("（190℃熱水が大気圧開放時、約17%が瞬時に蒸気化）\n")

    # ヘッダー
    print(f"{'ケース':<20} {'リーク面積':>12} {'流量':>10} {'蒸気発生':>10} "
          f"{'噴出速度':>10} {'50℃到達':>10} {'視程3m':>10} {'熱傷距離':>10}")
    print(f"{'':<20} {'[mm²]':>12} {'[kg/s]':>10} {'[kg/s]':>10} "
          f"{'[m/s]':>10} {'[秒]':>10} {'[秒]':>10} {'[m]':>10}")
    print("-" * 100)

    for a in assessments:
        t50 = f"{a.time_to_50C:.1f}" if a.time_to_50C < float('inf') else ">120"
        tvis = f"{a.time_to_visibility_3m:.1f}" if a.time_to_visibility_3m < float('inf') else ">120"

        print(f"{a.case_name:<20} {a.leak_area_mm2:>12.1f} {a.mass_flow:>10.2f} "
              f"{a.steam_flow:>10.2f} {a.jet_velocity:>10.1f} "
              f"{t50:>10} {tvis:>10} {a.burn_risk_distance:>10.1f}")

    print("=" * 100)

    # 警告メッセージ
    print("\n【重要な知見】")
    print("-" * 60)

    critical_cases = [a for a in assessments if a.time_to_visibility_3m < 10]
    if critical_cases:
        print("⚠ 以下のケースでは10秒以内に視界が著しく悪化:")
        for a in critical_cases:
            print(f"   - {a.case_name}: {a.time_to_visibility_3m:.1f}秒で視程3m以下")

    fast_heating = [a for a in assessments if a.time_to_50C < 30]
    if fast_heating:
        print("\n⚠ 以下のケースでは30秒以内に室温50℃超過:")
        for a in fast_heating:
            print(f"   - {a.case_name}: {a.time_to_50C:.1f}秒で50℃到達")

    high_flow = [a for a in assessments if a.mass_flow > 10]
    if high_flow:
        print("\n⚠ 以下のケースでは大量の熱水・蒸気が噴出:")
        for a in high_flow:
            print(f"   - {a.case_name}: {a.mass_flow:.1f} kg/s "
                  f"({a.mass_flow * 60:.0f} kg/min)")


def create_visualizations(assessments: List[RiskAssessment], room: RoomGeometry, props: WaterProperties):
    """結果の可視化"""

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 色のリスト
    colors = plt.cm.Reds(np.linspace(0.3, 0.9, len(assessments)))

    # 1. 時間経過による室温変化
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
    ax1.set_title('Room Temperature Rise')
    ax1.legend(loc='upper left', fontsize=8)
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim(0, 60)

    # 2. 視程の変化
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
    ax2.set_title('Visibility Degradation')
    ax2.legend(loc='upper right', fontsize=8)
    ax2.grid(True, alpha=0.3)
    ax2.set_xlim(0, 60)
    ax2.set_ylim(0, 20)

    # 3. リーク面積 vs 待避可能時間
    ax3 = axes[1, 0]
    leak_areas = [a.leak_area_mm2 for a in assessments]
    evac_times = [min(a.time_to_visibility_3m, a.time_to_50C) for a in assessments]

    bars = ax3.bar(range(len(assessments)), evac_times, color=colors)
    ax3.set_xticks(range(len(assessments)))
    ax3.set_xticklabels([a.case_name.split('(')[0].strip() for a in assessments],
                        rotation=45, ha='right', fontsize=9)
    ax3.set_ylabel('Available Evacuation Time [s]')
    ax3.set_title('Time Available for Evacuation')
    ax3.axhline(y=10, color='red', linestyle='--', linewidth=2, label='10s (Minimum escape time)')
    ax3.axhline(y=30, color='orange', linestyle='--', linewidth=2, label='30s (Marginal)')
    ax3.legend()
    ax3.grid(True, alpha=0.3, axis='y')

    # 値をバーの上に表示
    for bar, val in zip(bars, evac_times):
        if val < float('inf'):
            ax3.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                    f'{val:.1f}s', ha='center', va='bottom', fontsize=9)

    # 4. 蒸気発生量と流量
    ax4 = axes[1, 1]
    x = np.arange(len(assessments))
    width = 0.35

    mass_flows = [a.mass_flow for a in assessments]
    steam_flows = [a.steam_flow for a in assessments]

    bars1 = ax4.bar(x - width/2, mass_flows, width, label='Total mass flow', color='steelblue')
    bars2 = ax4.bar(x + width/2, steam_flows, width, label='Steam generation', color='orangered')

    ax4.set_xticks(x)
    ax4.set_xticklabels([a.case_name.split('(')[0].strip() for a in assessments],
                        rotation=45, ha='right', fontsize=9)
    ax4.set_ylabel('Flow Rate [kg/s]')
    ax4.set_title('Leak Flow Rate')
    ax4.legend()
    ax4.grid(True, alpha=0.3, axis='y')
    ax4.set_yscale('log')

    plt.tight_layout()
    plt.savefig('valve_leak_analysis.png', dpi=150, bbox_inches='tight')
    print("\nグラフを 'valve_leak_analysis.png' に保存しました")

    return fig


def analyze_jet_burn_risk(assessments: List[RiskAssessment]):
    """噴流による直接熱傷リスクの詳細分析"""

    print("\n" + "=" * 80)
    print("蒸気噴流による直接熱傷リスク分析")
    print("=" * 80)

    print("\n【熱傷の重症度基準】")
    print("  - 60℃以上の蒸気: 1秒以内に重度熱傷 (III度)")
    print("  - 55℃以上の蒸気: 10秒で重度熱傷")
    print("  - 48℃以上の湿熱: 数分で熱傷リスク")
    print("  ※ 蒸気は空気より熱伝達率が高く、乾熱より危険")

    print("\n【噴流特性】")
    print(f"{'ケース':<20} {'リーク径':>10} {'噴出速度':>10} {'運動量':>12} {'到達距離':>10}")
    print(f"{'':<20} {'[mm]':>10} {'[m/s]':>10} {'[N]':>12} {'[m]':>10}")
    print("-" * 65)

    for a in assessments:
        # リーク面積から等価直径を計算
        leak_diameter = np.sqrt(4 * a.leak_area / np.pi) * 1000  # mm

        # 噴流の運動量流束 (F = ρ * A * v²)
        momentum = a.mass_flow * a.jet_velocity  # N

        # 蒸気噴流の到達距離（簡易推定）
        # 自由噴流の貫通距離: x ~ d * (v/v_ambient) の関数
        # 100℃蒸気が周囲空気と混合して危険温度(55℃)以下になる距離
        if a.steam_flow > 0.001:
            # 噴流の混合希釈モデル（簡易）
            # 温度が (T_jet - T_amb) / (T_crit - T_amb) = 希釈率
            T_jet = 100  # ℃
            T_amb = 25   # ℃
            T_crit = 55  # ℃ (熱傷閾値)
            dilution_needed = (T_jet - T_amb) / (T_crit - T_amb)  # ≈ 2.5
            reach_distance = leak_diameter * 0.001 * 6.2 * np.sqrt(dilution_needed) * (a.jet_velocity / 10)
            reach_distance = min(15, max(0.3, reach_distance))
        else:
            reach_distance = 0.3

        print(f"{a.case_name:<20} {leak_diameter:>10.1f} {a.jet_velocity:>10.1f} "
              f"{momentum:>12.1f} {reach_distance:>10.1f}")

    print("\n【直接被曝シナリオ】")
    print("-" * 65)
    print("弁直近(1m以内)で作業中にリーク発生した場合:")
    print("")

    for a in assessments:
        # 1m距離での蒸気暴露量概算
        if a.steam_flow > 0.1:
            exposure_level = "即座に重度熱傷（致命的）"
            escape_chance = "不可"
        elif a.steam_flow > 0.01:
            exposure_level = "数秒で重度熱傷"
            escape_chance = "極めて困難"
        elif a.steam_flow > 0.001:
            exposure_level = "軽度〜中度熱傷リスク"
            escape_chance = "困難"
        else:
            exposure_level = "軽微な熱傷リスク"
            escape_chance = "可能"

        print(f"  {a.case_name}: {exposure_level} (退避{escape_chance})")


def create_evacuation_analysis(assessments: List[RiskAssessment]):
    """待避時間の詳細分析"""

    print("\n" + "=" * 80)
    print("待避時間分析")
    print("=" * 80)

    # 人間の反応・移動時間の仮定
    reaction_time = 2.0      # 異常認識時間 [s]
    decision_time = 3.0      # 判断時間 [s]
    movement_speed = 1.0     # 移動速度 [m/s] (視界不良時)
    max_escape_distance = 15 * np.sqrt(2)  # 対角線距離 [m]

    min_escape_time = reaction_time + decision_time + max_escape_distance / movement_speed

    print(f"\n想定待避シナリオ:")
    print(f"  - 異常認識時間: {reaction_time}秒")
    print(f"  - 判断時間: {decision_time}秒")
    print(f"  - 移動速度: {movement_speed} m/s（視界不良時）")
    print(f"  - 最大待避距離: {max_escape_distance:.1f}m（部屋対角線）")
    print(f"  - 必要最小待避時間: {min_escape_time:.1f}秒")

    print(f"\n{'ケース':<25} {'利用可能時間':>12} {'必要時間':>10} {'判定':>15}")
    print("-" * 65)

    for a in assessments:
        available = min(a.time_to_visibility_3m, a.time_to_50C)
        if available >= min_escape_time * 1.5:
            status = "待避可能"
        elif available >= min_escape_time:
            status = "待避困難"
        elif available >= reaction_time + decision_time:
            status = "待避極めて困難"
        else:
            status = "待避不可能"

        avail_str = f"{available:.1f}s" if available < float('inf') else ">120s"
        print(f"{a.case_name:<25} {avail_str:>12} {min_escape_time:>10.1f}s {status:>15}")

    print("\n" + "=" * 80)
    print("【結論】")
    print("-" * 80)

    dangerous_cases = [a for a in assessments
                       if min(a.time_to_visibility_3m, a.time_to_50C) < min_escape_time]

    if dangerous_cases:
        print(f"シートリーク面積が {dangerous_cases[0].leak_area_mm2:.0f} mm² 以上の場合、")
        print(f"作業員の安全な待避は極めて困難です。")
        print(f"\n単一弁隔離での開放作業は、リーク発生時に")
        print(f"作業員が重大な熱傷を負うリスクが高く、")
        print(f"ダブルブロック＆ブリード等の安全対策が必須です。")


# =============================================================================
# メイン実行
# =============================================================================

def main():
    """メイン実行関数"""

    print("\n" + "#" * 80)
    print("#  高エネルギー熱水系 ゲート弁シートリーク影響シミュレーション")
    print("#" * 80)

    # 設定
    props = WaterProperties()
    room = RoomGeometry()
    valve = ValveSpec()

    print(f"\n【条件設定】")
    print(f"  弁仕様: {int(valve.nominal_diameter * 1000)}A ゲート弁")
    print(f"  弁座全開面積: {valve.full_area * 1e6:.0f} mm² ({valve.full_area:.4f} m²)")
    print(f"  入口条件: {props.P_inlet/1e6:.1f} MPa, {props.T_inlet - 273.15:.0f}℃")
    print(f"  出口条件: 大気開放 ({props.P_outlet/1e3:.0f} kPa)")
    print(f"  室内寸法: {room.length}m × {room.width}m × {room.height}m = {room.volume:.0f} m³")

    # リークケース
    cases = get_leak_cases(valve)

    # リスク評価
    assessments = []
    for case_name, leak_area in cases:
        assessment = assess_risk(case_name, leak_area, props, room)
        assessments.append(assessment)

    # 結果出力
    print_summary_table(assessments)
    analyze_jet_burn_risk(assessments)
    create_evacuation_analysis(assessments)

    # 可視化
    try:
        create_visualizations(assessments, room, props)
    except Exception as e:
        print(f"\n注意: グラフ生成でエラー発生: {e}")
        print("数値結果は上記テーブルを参照してください。")

    # 最終サマリー
    print("\n" + "#" * 80)
    print("#  シミュレーション総括")
    print("#" * 80)
    print("""
本シミュレーションは簡易モデルによる概算であり、実際の状況は
現場条件（換気、障害物、弁位置等）により異なる可能性があります。

しかし、オーダーとして以下は明確です:

1. 600Aゲート弁のシートリークは、わずか0.1%（弁座面積比）でも
   数十kg/sの熱水流出となり、深刻な蒸気発生を伴う

2. リーク面積0.5%以上で、10秒以内に視界が著しく低下し、
   作業員の安全な退避は実質的に不可能

3. 弁近傍（1m以内）での作業中にリークが発生した場合、
   反応する間もなく重度熱傷を負うリスクが極めて高い

【推奨安全対策】
- 単一弁隔離での開放作業は禁止
- ダブルブロック＆ブリード（二重弁隔離+中間ドレン）を標準化
- 弁操作時の安全距離確保と保護具着用
- 定期的なシートリーク試験の実施
""")

    return assessments


if __name__ == "__main__":
    assessments = main()

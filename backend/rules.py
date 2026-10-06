"""填充因子闭区间判定。

每个温带各持一套 [ff_low, ff_high] 闭区间，闭区间端点也算合格。
判定只吃调用方在认领瞬间抄进抄本的上下限，本模块不读全局现行带。
"""


def judge(fill_factor: float, ff_low: float, ff_high: float, band_label: str = "") -> tuple[str, str]:
    where = f"{band_label}填充因子" if band_label else "填充因子"
    if ff_low <= fill_factor <= ff_high:
        return (
            "合格",
            f"{where} {fill_factor} 落在闭区间 [{ff_low}, {ff_high}] 内",
        )
    return (
        "衰减",
        f"{where} {fill_factor} 不在闭区间 [{ff_low}, {ff_high}] 内",
    )

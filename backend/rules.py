def judge(fill_factor: float, ff_min: float, ff_max: float) -> tuple[str, str]:
    """各温带各守一套闭区间 [ff_min, ff_max]，落在区间内合格，否则衰减。"""
    if ff_min <= fill_factor <= ff_max:
        return "合格", f"填充因子 {fill_factor} 落在闭区间 [{ff_min}, {ff_max}]"
    return "衰减", f"填充因子 {fill_factor} 超出闭区间 [{ff_min}, {ff_max}]"

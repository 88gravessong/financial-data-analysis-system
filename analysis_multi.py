#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analysis_multi.py
------------------------------------------------
支持多文件处理的财务数据分析模块
- 支持多个订单表文件合并
- 支持多个结算表文件合并
- 单个产品消耗表
"""

import pandas as pd
from pathlib import Path
from typing import List, Union

# 汇率设置
IDR_PER_RMB, IDR_PER_USD = 2300, 16000

def merge_order_files(order_files: List[Union[str, Path]]) -> pd.DataFrame:
    """合并多个订单表文件"""
    all_orders = []
    
    for file_path in order_files:
        try:
            df = pd.read_excel(file_path, dtype=str)
            # 标准化第一列为order_id
            df = df.rename(columns={df.columns[0]: "order_id"})
            all_orders.append(df)
            print(f"✅ 已读取订单文件: {Path(file_path).name} ({len(df)} 行)")
        except Exception as e:
            print(f"❌ 读取订单文件失败 {file_path}: {e}")
            raise
    
    if not all_orders:
        raise ValueError("没有成功读取任何订单文件")
    
    # 合并所有订单数据
    merged_orders = pd.concat(all_orders, ignore_index=True)
    print(f"📋 订单数据合并完成: 总计 {len(merged_orders)} 行")
    
    return merged_orders

def merge_settlement_files(settlement_files: List[Union[str, Path]]) -> pd.DataFrame:
    """合并多个结算表文件"""
    all_settlements = []
    
    for file_path in settlement_files:
        try:
            df = pd.read_excel(file_path, dtype=str)
            # 标准化第一列为order_id
            df = df.rename(columns={df.columns[0]: "order_id"})
            
            # 查找结算金额列
            settlement_col = None
            for col in df.columns:
                if "settlement" in col.lower():
                    settlement_col = col
                    break
            
            if settlement_col and settlement_col != "Total settlement amount":
                df = df.rename(columns={settlement_col: "Total settlement amount"})
            
            all_settlements.append(df)
            print(f"✅ 已读取结算文件: {Path(file_path).name} ({len(df)} 行)")
        except Exception as e:
            print(f"❌ 读取结算文件失败 {file_path}: {e}")
            raise
    
    if not all_settlements:
        raise ValueError("没有成功读取任何结算文件")
    
    # 合并所有结算数据
    merged_settlements = pd.concat(all_settlements, ignore_index=True)
    print(f"💳 结算数据合并完成: 总计 {len(merged_settlements)} 行")
    
    return merged_settlements

def process_financial_data(order_files: List[Union[str, Path]], 
                         settlement_files: List[Union[str, Path]], 
                         consumption_file: Union[str, Path],
                         output_dir: Union[str, Path] = ".") -> Path:
    """
    处理财务数据分析
    
    Args:
        order_files: 订单文件列表
        settlement_files: 结算文件列表  
        consumption_file: 产品消耗文件
        output_dir: 输出目录
        
    Returns:
        输出文件路径
    """
    
    print("🚀 开始财务数据分析...")
    
    # -------- 读取和合并文件 --------
    order = merge_order_files(order_files)
    settle = merge_settlement_files(settlement_files)
    cons = pd.read_excel(consumption_file, dtype=str)
    print(f"📊 已读取产品消耗文件: {Path(consumption_file).name} ({len(cons)} 行)")

    # -------- 数据预处理 --------
    # 处理结算金额
    if "Total settlement amount" not in settle.columns:
        settlement_cols = [c for c in settle.columns if "settlement" in c.lower()]
        if settlement_cols:
            settle = settle.rename(columns={settlement_cols[0]: "Total settlement amount"})
        else:
            raise ValueError("结算表中找不到结算金额列")
    
    settle["Total settlement amount"] = pd.to_numeric(settle["Total settlement amount"], errors="coerce")

    # 处理重复订单
    dup_settle = settle[settle.duplicated("order_id", keep=False)]
    settle = settle.drop_duplicates("order_id", keep=False)
    print(f"⚠️  排除重复结算订单: {len(dup_settle)} 行")

    # 合并订单和结算数据
    order = order.merge(settle[["order_id","Total settlement amount"]], on="order_id", how="left")

    # 识别关键列
    qty_col = None
    sku_col = None
    ship_col = None
    status_col = None
    
    for col in order.columns:
        if "数量" in col and qty_col is None:
            qty_col = col
        elif "sku" in col.lower() and sku_col is None:
            sku_col = col
        elif "是否出库" in col and ship_col is None:
            ship_col = col
        elif "平台状态" in col and status_col is None:
            status_col = col
    
    if not all([qty_col, sku_col, ship_col, status_col]):
        missing = []
        if not qty_col: missing.append("数量列")
        if not sku_col: missing.append("SKU列")
        if not ship_col: missing.append("是否出库列")
        if not status_col: missing.append("平台状态列")
        raise ValueError(f"订单表中缺少必要列: {', '.join(missing)}")

    print(f"📝 识别到关键列: 数量({qty_col}), SKU({sku_col}), 出库({ship_col}), 状态({status_col})")

    # 数据类型转换
    order[qty_col] = pd.to_numeric(order[qty_col], errors="coerce").fillna(0).astype(int)
    order["_shipped"] = order[ship_col].str.strip().str.lower()
    order["_status"] = order[status_col].str.strip().str.lower()

    # 计算每行结算金额和操作费
    lines = order.groupby("order_id")["order_id"].transform("size")
    order["settlement_per_line"] = order["Total settlement amount"] / lines

    # 运营费用计算
    tot_qty = order.groupby("order_id")[qty_col].transform("sum")
    order["order_fee_rmb"] = [
        2.0 if (s=="yes" and q==1) else 2.5 if (s=="yes" and q>1) else 0.0
        for s,q in zip(order["_shipped"], tot_qty)
    ]
    order["operation_fee_per_line_rmb"] = order.groupby("order_id")["order_fee_rmb"].transform("max") / lines

    # -------- SKU级别聚合 --------
    pair_df = order[[sku_col,"order_id","_shipped","_status"]].drop_duplicates([sku_col,"order_id"])

    # 订单级计数
    metrics = {
        "订单数": pair_df.groupby(sku_col)["order_id"].nunique(),
        "出库订单数": pair_df[pair_df["_shipped"]=="yes"].groupby(sku_col)["order_id"].nunique(),
        "签收订单数": pair_df[pair_df["_status"].isin(["delivered","completed"])]\
                     .groupby(sku_col)["order_id"].nunique(),
        "取消订单数": pair_df[pair_df["_status"]=="cancelled"].groupby(sku_col)["order_id"].nunique(),
        "出库前取消订单数": pair_df[(pair_df["_status"]=="cancelled") & (pair_df["_shipped"]=="no")]\
                         .groupby(sku_col)["order_id"].nunique(),
        "出库后取消订单数": pair_df[(pair_df["_status"]=="cancelled") & (pair_df["_shipped"]=="yes")]\
                         .groupby(sku_col)["order_id"].nunique(),
        "仍在途订单数": pair_df[pair_df["_status"]=="in transit"].groupby(sku_col)["order_id"].nunique(),
    }

    # 金额 & 数量聚合
    shipped_order = order[order["_shipped"] == "yes"]
    delivered_order = order[order["_status"].isin(["delivered","completed"])]
    
    base = order.groupby(sku_col).agg(
        sku_total_settlement    = ("settlement_per_line", "sum"),
        sku_total_operation_fee = ("operation_fee_per_line_rmb", "sum")
    )
    
    # 出库数量
    shipped_qty = shipped_order.groupby(sku_col)[qty_col].sum()
    base = base.join(shipped_qty.rename("出库数量"), how="left")
    
    # 签收金额  
    delivered_amount = delivered_order.groupby(sku_col)["settlement_per_line"].sum()
    base = base.join(delivered_amount.rename("签收金额"), how="left")

    sku = base
    for k,v in metrics.items(): 
        sku = sku.join(v.rename(k), how="left")
    sku = sku.fillna(0)

    # 运营率计算
    sku["签收率"] = sku["签收订单数"] / sku["订单数"]
    sku["取消率"] = sku["取消订单数"] / sku["订单数"]
    sku["出库前取消率"] = sku["出库前取消订单数"] / sku["订单数"]
    sku["出库后取消率"] = sku["出库后取消订单数"] / sku["订单数"]
    sku["仍在途率"] = sku["仍在途订单数"] / sku["订单数"]
    sku = sku.drop(columns=["取消订单数","出库前取消订单数","出库后取消订单数","仍在途订单数"])

    # -------- 产品消耗数据处理 --------
    if sku_col not in cons.columns:
        cons = cons.rename(columns={cons.columns[0]: sku_col})
    
    # 数值列转换
    for c in cons.columns:
        if c != sku_col: 
            cons[c] = pd.to_numeric(cons[c], errors="coerce")
    
    # 确保必要列存在
    for col in ["印尼盾ads消耗","印尼盾gmvmax消耗","印尼盾单sku成本"]:
        if col not in cons.columns: 
            cons[col] = 0.0

    # 货币转换
    cons["美金ads消耗"] = cons["印尼盾ads消耗"] / IDR_PER_USD
    cons["美金gmvmax消耗"] = cons["印尼盾gmvmax消耗"] / IDR_PER_USD
    cons["人民币单sku成本"] = cons["印尼盾单sku成本"] / IDR_PER_RMB

    # 合并消耗数据
    keep = [sku_col,"印尼盾ads消耗","印尼盾gmvmax消耗","美金ads消耗",
            "美金gmvmax消耗","印尼盾单sku成本","人民币单sku成本"]
    sku = sku.merge(cons[keep], on=sku_col, how="left").fillna(0)

    # -------- 财务指标计算 --------
    sku["印尼盾操作费"] = sku["sku_total_operation_fee"] * IDR_PER_RMB
    sku["印尼盾消耗"] = sku["印尼盾ads消耗"] + sku["印尼盾gmvmax消耗"]
    sku["印尼盾产品成本"] = sku["印尼盾单sku成本"] * sku["出库数量"]

    sku["利润"] = sku["sku_total_settlement"] - sku["印尼盾操作费"] - sku["印尼盾产品成本"] - sku["印尼盾消耗"]
    sku["人民币利润"] = sku["利润"] / IDR_PER_RMB
    sku["签收毛利率"] = sku["利润"] / sku["签收金额"].replace(0, pd.NA)
    sku["每单利润"] = sku["人民币利润"] / sku["签收订单数"].replace(0, pd.NA)

    # -------- 输出结果 --------
    output_path = Path(output_dir) / "财务分析结果_多文件.xlsx"
    
    with pd.ExcelWriter(output_path, engine="openpyxl") as w:
        # 订单表（含结算与操作费）
        order.to_excel(w, sheet_name="订单表_含结算与操作费", index=False)
        
        # SKU汇总（结算与操作费）
        sku[["sku_total_settlement","sku_total_operation_fee"]].reset_index()\
           .to_excel(w, sheet_name="sku汇总_结算与操作费", index=False)
        
        # 排除的重复订单
        if len(dup_settle) > 0:
            dup_settle.to_excel(w, sheet_name="排除订单_多行结算", index=False)
        
        # SKU财务指标
        cols = sku.columns.tolist()
        if "印尼盾操作费" in cols:
            # 将印尼盾操作费移到前面
            cols.insert(3, cols.pop(cols.index("印尼盾操作费")))
        sku[cols].reset_index().to_excel(w, sheet_name="sku财务指标", index=False)
    
    print(f"✅ 分析完成! 结果已保存到: {output_path}")
    print(f"📈 处理了 {len(order_files)} 个订单文件, {len(settlement_files)} 个结算文件")
    print(f"📊 总计订单: {len(order)} 行, SKU数量: {len(sku)} 个")
    
    return output_path

if __name__ == "__main__":
    # 测试用例
    test_order_files = ["1-2月bigseller订单表跑6.xlsx"]
    test_settlement_files = ["跑6结算表结算时间1-3月.xlsx"]
    test_consumption_file = "产品消耗表.xlsx"
    
    # 检查测试文件是否存在
    missing_files = []
    for f in test_order_files + test_settlement_files + [test_consumption_file]:
        if not Path(f).exists():
            missing_files.append(f)
    
    if missing_files:
        print(f"❌ 找不到测试文件: {missing_files}")
        print("请确保测试文件存在或直接通过 Flask 应用使用此模块")
    else:
        process_financial_data(
            order_files=test_order_files,
            settlement_files=test_settlement_files,
            consumption_file=test_consumption_file
        ) 
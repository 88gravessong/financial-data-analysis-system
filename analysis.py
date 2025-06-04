#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calc_all_financial_v5.py
------------------------------------------------
核心修正：
  - 出库数量 = 该 SKU 所有出库行数量字段之和（_shipped=='yes'）
  - 印尼盾产品成本 = 印尼盾单sku成本 × 出库数量
  - 利润公式同步更新
依赖: pandas, openpyxl
"""

import pandas as pd
from pathlib import Path

ORDER_FILE, SETTLE_FILE, CONSUME_FILE = (
    "1-2月bigseller订单表跑6.xlsx",
    "跑6结算表结算时间1-3月.xlsx",
    "产品消耗表.xlsx",
)
OUTPUT_FILE = "综合财务指标结果_v5.xlsx"
IDR_PER_RMB, IDR_PER_USD = 2300, 16000

def main():
    # -------- 读取 --------
    order  = pd.read_excel(ORDER_FILE, dtype=str)
    settle = pd.read_excel(SETTLE_FILE, dtype=str)
    cons   = pd.read_excel(CONSUME_FILE, dtype=str)

    order  = order.rename(columns={order.columns[0]: "order_id"})
    settle = settle.rename(columns={settle.columns[0]: "order_id"})

    if "Total settlement amount" not in settle.columns:
        settle = settle.rename(columns={ [c for c in settle.columns if "settlement" in c.lower()][0]:
                                         "Total settlement amount"})
    settle["Total settlement amount"] = pd.to_numeric(settle["Total settlement amount"], errors="coerce")

    dup_settle = settle[settle.duplicated("order_id", keep=False)]
    settle     = settle.drop_duplicates("order_id", keep=False)
    order = order.merge(settle[["order_id","Total settlement amount"]], on="order_id", how="left")

    qty_col    = [c for c in order.columns if "数量" in c][0]
    sku_col    = [c for c in order.columns if "sku" in c.lower()][0]
    ship_col   = [c for c in order.columns if "是否出库" in c][0]
    status_col = [c for c in order.columns if "平台状态" in c][0]

    order[qty_col] = pd.to_numeric(order[qty_col], errors="coerce").fillna(0).astype(int)
    order["_shipped"] = order[ship_col].str.strip().str.lower()
    order["_status"]  = order[status_col].str.strip().str.lower()

    # settlement_per_line
    lines = order.groupby("order_id")["order_id"].transform("size")
    order["settlement_per_line"] = order["Total settlement amount"] / lines

    # operation fee per line (RMB)
    tot_qty = order.groupby("order_id")[qty_col].transform("sum")
    order["order_fee_rmb"] = [
        2.0 if (s=="yes" and q==1) else 2.5 if (s=="yes" and q>1) else 0.0
        for s,q in zip(order["_shipped"], tot_qty)
    ]
    order["operation_fee_per_line_rmb"] = order.groupby("order_id")["order_fee_rmb"].transform("max") / lines

    # -------- 预聚合辅助 --------
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

    # 金额 & 数量 - 修正聚合方式
    # 分别处理不同条件的数据
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

    # 运营率
    sku["签收率"]      = sku["签收订单数"] / sku["订单数"]
    sku["取消率"]      = sku["取消订单数"] / sku["订单数"]
    sku["出库前取消率"] = sku["出库前取消订单数"] / sku["订单数"]
    sku["出库后取消率"] = sku["出库后取消订单数"] / sku["订单数"]
    sku["仍在途率"]    = sku["仍在途订单数"] / sku["订单数"]
    sku = sku.drop(columns=["取消订单数","出库前取消订单数","出库后取消订单数","仍在途订单数"])

    # -------- 消耗 & 成本 --------
    if sku_col not in cons.columns:
        cons = cons.rename(columns={cons.columns[0]: sku_col})
    for c in cons.columns:
        if c != sku_col: cons[c] = pd.to_numeric(cons[c], errors="coerce")
    for col in ["印尼盾ads消耗","印尼盾gmvmax消耗","印尼盾单sku成本"]:
        if col not in cons.columns: cons[col] = 0.0

    cons["美金ads消耗"]   = cons["印尼盾ads消耗"] / IDR_PER_USD
    cons["美金gmvmax消耗"] = cons["印尼盾gmvmax消耗"] / IDR_PER_USD
    cons["人民币单sku成本"] = cons["印尼盾单sku成本"] / IDR_PER_RMB

    keep = [sku_col,"印尼盾ads消耗","印尼盾gmvmax消耗","美金ads消耗",
            "美金gmvmax消耗","印尼盾单sku成本","人民币单sku成本"]
    sku = sku.merge(cons[keep], on=sku_col, how="left").fillna(0)

    # -------- 财务指标 --------
    sku["印尼盾操作费"]   = sku["sku_total_operation_fee"] * IDR_PER_RMB
    sku["印尼盾消耗"]     = sku["印尼盾ads消耗"] + sku["印尼盾gmvmax消耗"]
    sku["印尼盾产品成本"] = sku["印尼盾单sku成本"] * sku["出库数量"]

    sku["利润"]       = sku["sku_total_settlement"] - sku["印尼盾操作费"] - sku["印尼盾产品成本"] - sku["印尼盾消耗"]
    sku["人民币利润"]  = sku["利润"] / IDR_PER_RMB
    sku["签收毛利率"]  = sku["利润"] / sku["签收金额"].replace(0, pd.NA)
    sku["每单利润"]   = sku["人民币利润"] / sku["签收订单数"].replace(0, pd.NA)

    # -------- 输出 --------
    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as w:
        order.to_excel(w, sheet_name="订单表_含结算与操作费", index=False)
        sku[["sku_total_settlement","sku_total_operation_fee"]].reset_index()\
           .to_excel(w, sheet_name="sku汇总_结算与操作费", index=False)
        dup_settle.to_excel(w, sheet_name="排除订单_多行结算", index=False)
        cols = sku.columns.tolist()
        if "印尼盾操作费" in cols:
            cols.insert(3, cols.pop(cols.index("印尼盾操作费")))
        sku[cols].reset_index().to_excel(w, sheet_name="sku财务指标", index=False)
    print("✅ 生成:", OUTPUT_FILE)

if __name__ == "__main__":
    for f in (ORDER_FILE, SETTLE_FILE, CONSUME_FILE):
        if not Path(f).exists(): raise FileNotFoundError(f)
    main()

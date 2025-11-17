# libraries
import streamlit as st
import pandas as pd
import numpy as np
import os
import io
import json
from datetime import datetime
import plotly.graph_objects as go

# Try to use numpy_financial for robust IRR; fallback to numpy
try:
    import numpy_financial as nf
    _HAS_NF = True
except Exception:
    _HAS_NF = False

# -------------------------
# Paths and folders
# -------------------------
DATA_DIR = "data"
SCENARIO_DIR = os.path.join(DATA_DIR, "scenarios")
PARAM_FILE = os.path.join(DATA_DIR, "parameters.json")
os.makedirs(SCENARIO_DIR, exist_ok=True)

# -------------------------
# Helpers
# -------------------------
def eur_format(x):
    """Return European currency formatted string with euro sign, e.g. € 12.345,67"""
    try:
        x = float(x)
        neg = x < 0
        x = abs(x)
        euros = int(x)
        cents = int(round((x - euros) * 100))
        euros_str = f"{euros:,}".replace(",", ".")
        s = f"€ {euros_str},{cents:02d}"
        return f"-{s}" if neg else s
    except Exception:
        return x

def simple_npv(rate, cashflows):
    return sum([cf / ((1 + rate) ** i) for i, cf in enumerate(cashflows)])

def compute_irr(cashflows):
    # try numpy_financial
    try:
        if _HAS_NF:
            irr_val = nf.irr(cashflows)
        else:
            # numpy's irr may show deprecation in some versions; still usable as fallback
            irr_val = np.irr(cashflows)
        if irr_val is None or (isinstance(irr_val, float) and np.isnan(irr_val)):
            return None
        return float(irr_val)
    except Exception:
        return None

def annuity_payment(principal, annual_rate, years):
    if years <= 0:
        return 0.0
    r = annual_rate
    if r == 0:
        return principal / years
    a = principal * (r * (1 + r) ** years) / ((1 + r) ** years - 1)
    return a

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_json(path, default=None):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def write_excel_bytes(dfs: dict):
    # dfs: dict sheetname -> dataframe
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        for sheet, df in dfs.items():
            # ensure sheet name length <= 31
            sheetname = sheet[:31]
            df.to_excel(writer, sheet_name=sheetname, index=False)
        writer.save()
    return out.getvalue()

# -------------------------
# Default parameters
# -------------------------
DEFAULT_PARAMS = {
    "currency": "EUR",
    "discount_rate": 0.03,
    "working_hours_per_year": 8765,
    "output_kg_per_m3_per_year": 36.5,
    "capex_table": {40: 1_000_000, 45: 1_200_000, 60: 1_500_000, 80: 1_750_000, 90: 2_000_000, 120: 2_750_000},
    "selling_prices": {"Haematococcus": 233.75, "Klamath": 233.75, "Dunaliella Salina": 233.75, "Spirulina": 125.00},
    "tax_threshold": 200_000.0, 
    "tax_rate_below": 0.19,
    "tax_rate_above": 0.258,
    "revenue_growth": 0.0,
    "opex_growth": 0.0,
    # energy defaults
    "network_taxes": 0.03,
    "kwh_M3_Hour": 1.0833
}

# -------------------------
# Load parameters (persistent)
# -------------------------
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)

params = load_json(PARAM_FILE, default=DEFAULT_PARAMS.copy())
# ensure missing keys set from defaults
for k, v in DEFAULT_PARAMS.items():
    if k not in params:
        params[k] = v

# -------------------------
# Load persistent scenarios into session state
# -------------------------
if "scenarios" not in st.session_state:
    st.session_state["scenarios"] = {}
    # load JSONs
    for fname in os.listdir(SCENARIO_DIR):
        if fname.endswith(".json"):
            try:
                sc = load_json(os.path.join(SCENARIO_DIR, fname))
                if sc and "name" in sc:
                    st.session_state["scenarios"][sc["name"]] = sc
            except Exception:
                pass

# -------------------------
# Session state defaults (Modelberekening)
# -------------------------
MODEL_DEFAULTS = {
    "equity_pct": 20.0,
    "loan_interest": 6.0,
    "loan_term": 5,
    "grace_period": 0,
    "contract_type": "Fixed",
    "fixed_price": 0.12,
    "flex_day_price": 0.15,
    "flex_night_price": 0.07,
    "pct_day": 0.66,
    "proj_years": 15,
    "annual_self_generation_kwh": 0,
    "start_year": datetime.now().year,
    # UI selections:
    "algae_type": list(params.get("selling_prices", {}).keys())[0] if params.get("selling_prices") else "Klamath",
    "scale": sorted([int(k) for k in params.get("capex_table", {}).keys()])[0] if params.get("capex_table") else 60,
    "selected_year_for_pl": None,
}

for k, v in MODEL_DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# -------------------------
# UI Layout and pages
# -------------------------
st.set_page_config(page_title="Algae Financial Model", layout="wide")
st.title("Algae Financial Model")

page = st.sidebar.radio("Pagina", ["Modelberekening", "Parameters & Assumpties",  "Scenario's"])

# -------------------------
# PARAMETERS PAGE
# -------------------------
if page == "Parameters & Assumpties":
    st.header("Parameters & Assumpties")
    st.write("Wijzig hier de vaste aannames. Klik 'Opslaan' om persistent op te slaan.")

    with st.form("params_form"):
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Algemeen")
            currency = st.selectbox("Currency", ["EUR", "USD", "GBP"], index=["EUR","USD","GBP"].index(params.get("currency","EUR")))
            discount_rate = st.number_input("Discount rate (NPV, %)", value=float(params.get("discount_rate",0.03)*100))/100
            working_hours = st.number_input("Working hours per year", value=float(params.get("working_hours_per_year",8765)))
            output_kg_m3 = st.number_input("Output (kg/m³/yr)", value=float(params.get("output_kg_per_m3_per_year",36.5)))
        with col2:
            st.subheader("Belastingen")
            tax_threshold = st.number_input("Tax threshold (EUR)", value=float(params.get("tax_threshold",200000.0)))
            tax_rate_below = st.number_input("Tax rate if profit ≤ threshold (%)", value=float(params.get("tax_rate_below",0.19)*100))/100
            tax_rate_above = st.number_input("Tax rate if profit > threshold (%)", value=float(params.get("tax_rate_above",0.258)*100))/100
            
        st.subheader("CAPEX per scale (wijzig rijen hieronder)")
        # ensure capex keys are numeric-friendly for display
        capex_items = params.get("capex_table", DEFAULT_PARAMS["capex_table"])
        # If JSON stored keys are strings, convert to ints where possible
        capex_items_norm = {}
        for k,v in capex_items.items():
            try:
                capex_items_norm[int(k)] = float(v)
            except Exception:
                try:
                    capex_items_norm[int(str(k))] = float(v)
                except Exception:
                    pass
        if not capex_items_norm:
            capex_items_norm = DEFAULT_PARAMS["capex_table"]
        capex_df = pd.DataFrame([{"Scale (m3)": k, "CAPEX (€)": v} for k,v in sorted(capex_items_norm.items())])
        st.table(capex_df.reset_index(drop=True))

        # allow adding or editing via inputs below
        capex_edit_col1, capex_edit_col2, capex_edit_col3 = st.columns([1,1,1])
        with capex_edit_col1:
            new_scale = st.number_input("Nieuw: Scale (m³)", value=60, step=5)
        with capex_edit_col2:
            new_capex = st.number_input(
                "Nieuw: CAPEX (€)",
                value=float(capex_items_norm.get(new_scale, 1500000.0)),
                step=1000.0,
                format="%.2f"
            )

        with capex_edit_col3:
            if st.form_submit_button("Voeg / update CAPEX rij"):
                capex_items_norm[int(new_scale)] = float(new_capex)
                params["capex_table"] = capex_items_norm
                save_json(PARAM_FILE, params)
                st.success(f"CAPEX voor schaal {new_scale} bijgewerkt.")
                st.rerun()

        st.subheader("Selling prices per algae type")
        selling_prices = params.get("selling_prices", DEFAULT_PARAMS["selling_prices"])
        # edit selling prices as individual inputs
        cols = st.columns(2)
        edited_selling = {}
        keys = list(selling_prices.keys())
        for i, key in enumerate(keys):
            with cols[i % 2]:
                edited_selling[key] = st.number_input(f"{key} selling price (EUR/kg)", value=float(selling_prices[key]))
        st.subheader("Energie instellingen")
        col_e1, col_e2 = st.columns(2)
        with col_e1:
            opex_growth = st.number_input("OPEX growth p.a. (%)", value=params.get("opex_growth",0.0)*100.0, step=0.1)/100.0
            revenue_growth = st.number_input("Revenue growth p.a. (%)", value=params.get("revenue_growth",0.0)*100.0, step=0.1)/100.0
        with col_e2:
            kwh_M3_Hour = st.number_input("Electricity consumption (kWh/m³/hr)", value=float(params.get("kwh_M3_Hour",1.0833)))
            network_taxes = st.number_input("Network & taxes (EUR/kWh)", value=float(params.get("network_taxes",0.03)))

        submitted = st.form_submit_button("Opslaan alle parameters")
        if submitted:
            params["currency"] = currency
            params["discount_rate"] = discount_rate
            params["working_hours_per_year"] = working_hours
            params["output_kg_per_m3_per_year"] = output_kg_m3
            params["tax_threshold"] = tax_threshold
            params["tax_rate_below"] = tax_rate_below
            params["tax_rate_above"] = tax_rate_above
            params["selling_prices"] = edited_selling
            params["opex_growth"] = opex_growth
            params["revenue_growth"] = revenue_growth
            params["kwh_M3_Hour"] = kwh_M3_Hour
            params["network_taxes"] = network_taxes
            params["capex_table"] = capex_items_norm
            save_json(PARAM_FILE, params)
            st.success("Parameters persistent opgeslagen.")
            st.rerun()

# -------------------------
# MODEL PAGE
# -------------------------
elif page == "Modelberekening":
    st.header("Modelberekening")
    st.write("Compacte invoer; vaste parameters uit 'Parameters & Assumpties' worden gebruikt (niet bewerkbaar hier).")

    # load fixed parameters from params
    selling_prices = params["selling_prices"]
    capex_table = params["capex_table"]
    discount_rate = params["discount_rate"]
    tax_threshold = params["tax_threshold"]
    tax_rate_below = params["tax_rate_below"]
    tax_rate_above = params["tax_rate_above"]
    output_per_m3 = params["output_kg_per_m3_per_year"]
    revenue_growth = params.get("revenue_growth", 0.0)
    opex_growth = params.get("opex_growth", 0.0)

    # ensure capex_table keys are ints for selection
    capex_table_norm = {}
    for k,v in capex_table.items():
        try:
            capex_table_norm[int(k)] = float(v)
        except Exception:
            pass
    if not capex_table_norm:
        capex_table_norm = {60: 1500000.0}
    scales_sorted = sorted(capex_table_norm.keys())

    # -------------------------
    # FIXED INFO DISPLAY
    # -------------------------
    c1, c2, c3 = st.columns([1,1,1])
    with c2:
        st.caption("Select scale (M³)")
        # use session_state.scale as default index if present in list
        default_scale = st.session_state.get("scale", scales_sorted[0] if scales_sorted else 60)
        if default_scale not in scales_sorted:
            default_scale = scales_sorted[0]
            st.session_state["scale"] = default_scale
        scale = st.selectbox("Scale (M³)", scales_sorted, index=scales_sorted.index(default_scale), key="scale")
        # Fix voor string keys in capex_table (JSON)
        capex_selected = float(capex_table_norm.get(int(scale), capex_table_norm.get(scale, 0.0)))
        st.caption("CAPEX selected — niet bewerkbaar")
        st.markdown(f"**{eur_format(capex_selected)}**")
        st.caption("Output (kg/m³/yr)")
        st.markdown(f"**{output_per_m3}**")

        # fixed production calculation
        production_fixed = output_per_m3 * scale if 'scale' in locals() else 0.0     

    with c1:
        default_algae = st.session_state.get("algae_type", list(selling_prices.keys())[0] if selling_prices else "Spirulina")
        algae_type = st.selectbox("Algae type", list(selling_prices.keys()), index=list(selling_prices.keys()).index(default_algae) if default_algae in selling_prices else 0, key="algae_type")
        st.caption("Selling price (EUR/kg) — niet bewerkbaar hier")
        st.markdown(f"**{eur_format(selling_prices[algae_type])}**")
        st.caption("Production (kg/yr) — niet bewerkbaar")
        st.markdown(f"**{production_fixed:,.0f} kg/yr**") 

    with c3:
        st.caption("Discount rate (NPV) — niet bewerkbaar")
        st.markdown(f"**{discount_rate*100:.2f}%**")
        st.caption("Tax rule (automatic)")
        st.markdown(f"**{tax_rate_below*100:.2f}% if profit ≤ {eur_format(tax_threshold)}, else {tax_rate_above*100:.2f}%**")
        st.caption("total electricity consumption (kwh/yr) — niet bewerkbaar")
        st.markdown(f"**{(params.get('kwh_M3_Hour',1.0833) * params.get('working_hours_per_year',8765) * scale):.0f} kWh/yr**"
        )                 

    st.markdown("---")
    # --------------------------------
    # 🔧 PERSISTENT INPUTS (session_state-backed)
    # --------------------------------
    left, mid, right = st.columns([1,1,1])

    with left:
        st.number_input("Equity %", key="equity_pct", step=1.0)
        st.number_input("Loan interest (annual %)", key="loan_interest", step=0.1)

    with mid:
        st.number_input("Loan term (years)", key="loan_term")
        st.number_input("Grace period (years)", key="grace_period")

    with right:
        st.selectbox(
            "Contract type",
            ["Fixed", "Flexible"],
            key="contract_type",
        )

        if st.session_state.contract_type == "Fixed":
            st.number_input("Fixed electricity price", key="fixed_price")
            # ensure flex fields exist but not shown
            if "flex_day_price" not in st.session_state:
                st.session_state["flex_day_price"] = MODEL_DEFAULTS["flex_day_price"]
            if "flex_night_price" not in st.session_state:
                st.session_state["flex_night_price"] = MODEL_DEFAULTS["flex_night_price"]
            if "pct_day" not in st.session_state:
                st.session_state["pct_day"] = MODEL_DEFAULTS["pct_day"]
        else:
            st.number_input("Flex day price", key="flex_day_price")
            st.number_input("Flex night price", key="flex_night_price")
            # slider stores integer percent then convert
            pct_int = st.slider("% consumption in day time", 0, 100, int(st.session_state.pct_day * 100), key="pct_day_slider")
            st.session_state.pct_day = pct_int / 100.0
            # ensure fixed_price exists
            if "fixed_price" not in st.session_state:
                st.session_state["fixed_price"] = MODEL_DEFAULTS["fixed_price"]

    # --------------------------------
    # Projection settings (persistent)
    # --------------------------------
    p1, p2 = st.columns([1,1])
    with p1:
        st.number_input("Projection years", key="proj_years")

    with p2:
        st.number_input("Annual self-generation (kWh)", key="annual_self_generation_kwh")
        st.number_input("Start year", key="start_year")

    # --------------------------------
    # CORE MODEL CALCULATIONS
    # --------------------------------
    equity_pct = st.session_state.equity_pct
    loan_interest = st.session_state.loan_interest
    loan_term = st.session_state.loan_term
    grace_period = st.session_state.grace_period
    contract_type = st.session_state.contract_type
    fixed_price = st.session_state.fixed_price
    flex_day_price = st.session_state.flex_day_price
    flex_night_price = st.session_state.flex_night_price
    pct_day = st.session_state.pct_day
    proj_years = st.session_state.proj_years
    annual_self_generation_kwh = st.session_state.annual_self_generation_kwh
    start_year = st.session_state.start_year
    algae_type = st.session_state.algae_type
    scale = st.session_state.scale

    # (vanaf hier is jouw originele berekeningen/code)
    selling_price = float(selling_prices[algae_type])
    effective_sales = production_fixed
    revenue_year1 = effective_sales * selling_price

    # OPEX base items
    staff_cost = 0.3 * 55000  # example
    sla_cost = 1_500_000 * 0.08  # placeholder
    # energy calculations (self generation reduces purchased kWh)
    self_generated_energy = int(annual_self_generation_kwh)
    baseline_electricity_consumption = params.get("kwh_M3_Hour", 1.0833) * params.get("working_hours_per_year", 8765) * scale if 'scale' in locals() else 0.0
    purchased_kwh = max(baseline_electricity_consumption - self_generated_energy, 0.0)

    if contract_type == "Flexible":
        day_frac = pct_day if pct_day is not None else 0.66
        purchase_price = day_frac * flex_day_price + (1 - day_frac) * flex_night_price
    else:
        purchase_price = fixed_price

    network_taxes = params.get("network_taxes", 0.0)
    electricity_cost_total = purchased_kwh * (purchase_price + network_taxes)   # net electricity cost
    total_opex_year1 = staff_cost + sla_cost + electricity_cost_total

    # CAPEX and financing
    total_capex = capex_selected
    equity = total_capex * (equity_pct / 100.0)
    loan_principal = total_capex - equity
    annual_loan_rate = float(loan_interest) / 100.0

    repay_years = max(int(loan_term) - int(grace_period), 0)
    annuity_after_grace = annuity_payment(loan_principal, annual_loan_rate, repay_years) if repay_years > 0 else 0.0

    # Build cashflow and loan schedules
    cashflow_rows = []
    loan_rows = []
    outstanding = loan_principal
    # iterate n=0..proj_years where n=0 => start_year (first operational year with revenue), capex outflow included in that year
    revenue_n = revenue_year1
    opex_n = total_opex_year1

    for n in range(0, int(proj_years)+1):
        year_label = int(start_year + n)
        if n == 0:
            revenue_cur = revenue_year1
            opex_cur = total_opex_year1
        else:
            revenue_cur = revenue_cur * (1 + revenue_growth)
            opex_cur = opex_cur * (1 + opex_growth)

        # interest based on outstanding at start of year
        interest = outstanding * annual_loan_rate if outstanding > 0 else 0.0

        principal_repay = 0.0
        if n < int(grace_period):
            principal_repay = 0.0
        else:
            if repay_years > 0 and outstanding > 0:
                payment = annuity_after_grace
                interest_comp = outstanding * annual_loan_rate
                principal_comp = max(0.0, payment - interest_comp)
                principal_repay = min(principal_comp, outstanding)
                outstanding = max(0.0, outstanding - principal_repay)

        ebit = revenue_cur - opex_cur
        ebt = ebit - interest
        tax_rate_applied = tax_rate_above if ebt > tax_threshold else tax_rate_below
        tax = ebt * tax_rate_applied if ebt > 0 else 0.0
        net_income = ebt - tax

        capex_outflow = total_capex if n == 0 else 0.0
        free_cash_flow = net_income - principal_repay - capex_outflow

        cashflow_rows.append({
            "Year": year_label,
            "Revenue": revenue_cur,
            "OPEX": opex_cur,
            "Interest": interest,
            "EBT": ebt,
            "Tax": tax,
            "Net Income": net_income,
            "Principal Repayment": principal_repay,
            "Capex Outflow": capex_outflow,
            "Free Cash Flow": free_cash_flow
        })

        loan_rows.append({
            "Year": year_label,
            "Start Balance": (outstanding + principal_repay),
            "Interest": interest,
            "Principal Repayment": principal_repay,
            "End Balance": outstanding
        })

    cashflow_df = pd.DataFrame(cashflow_rows)
    loan_df = pd.DataFrame(loan_rows)

    # Trim loan_df to the year loan is repaid (first End Balance == 0)
    if not loan_df.empty:
        zeros = loan_df[loan_df["End Balance"] <= 0.0]
        if not zeros.empty:
            last_idx = zeros.index[0]
            loan_df = loan_df.loc[:last_idx].reset_index(drop=True)

    # KPIs
    cashflows_for_npv = list(cashflow_df["Free Cash Flow"].fillna(0.0).values)
    model_npv = simple_npv(discount_rate, cashflows_for_npv)
    model_irr = compute_irr(cashflows_for_npv)

    # Year selection for P&L view (dropdown)
    available_years = list(cashflow_df["Year"].astype(int).tolist())
    # default selected year is first year unless the user previously picked one
    if st.session_state.get("selected_year_for_pl") in available_years:
        idx_default = available_years.index(st.session_state.get("selected_year_for_pl"))
    else:
        idx_default = 0
        st.session_state["selected_year_for_pl"] = available_years[0] if available_years else None
    selected_year = st.selectbox("Selecteer jaar voor P&L weergave", available_years, index=idx_default, key="selected_year_for_pl")
    # extract row
    pl_row = cashflow_df[cashflow_df["Year"] == selected_year].iloc[0]
    pl_display = pd.DataFrame({
        "Line": ["Revenue", "OPEX", "Interest", "EBT", "Tax", "Net income"],
        "Value": [pl_row["Revenue"], pl_row["OPEX"], pl_row["Interest"], pl_row["EBT"], pl_row["Tax"], pl_row["Net Income"]]
    })
    pl_display["Value"] = pl_display["Value"].apply(eur_format)
    st.subheader(f"P&L - jaar {selected_year}")
    st.table(pl_display.reset_index(drop=True))

    # Big KPI display (no truncation)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Revenue (yr 1)", eur_format(cashflow_df.loc[0,"Revenue"]))
    k2.metric("Total OPEX (yr 1)", eur_format(cashflow_df.loc[0,"OPEX"]))
    k3.metric("Net income (yr 1)", eur_format(cashflow_df.loc[0,"Net Income"]))
    roi_text = f"{(cashflow_df.loc[0,'Net Income'] / equity * 100):.1f}%" if equity > 0 else "N/A"
    k4.metric("ROI on Equity (yr 1)", roi_text)

    st.markdown("---")
    st.subheader("Investment KPIs")
    kpi_df = pd.DataFrame({
        "Metric": ["Total Investment (CAPEX)", "Equity", "Loan principal", "Annuity (after grace)", "NPV (discount rate)", "IRR (project)"],
        "Value": [eur_format(total_capex), eur_format(equity), eur_format(loan_principal), eur_format(annuity_after_grace),
                  eur_format(model_npv), f"{(model_irr*100):.2f}%" if model_irr is not None else "N/A"]
    })
    st.table(kpi_df.reset_index(drop=True))

    # Cashflow table (no index)
    st.subheader("Cashflow overzicht")
    display_cf = cashflow_df.copy()
    for col in ["Revenue","OPEX","Interest","EBT","Tax","Net Income","Principal Repayment","Capex Outflow","Free Cash Flow"]:
        display_cf[col] = display_cf[col].apply(eur_format)
    st.dataframe(display_cf.reset_index(drop=True), use_container_width=True)

    # Loan amortization
    st.subheader("Loan amortization schedule (stopt bij volledige aflossing)")
    if not loan_df.empty:
        loan_disp = loan_df.copy()
        for col in ["Start Balance","Interest","Principal Repayment","End Balance"]:
            loan_disp[col] = loan_disp[col].apply(eur_format)
        st.dataframe(loan_disp.reset_index(drop=True), use_container_width=True)
    else:
        st.write("Geen leningsschema (geen lening of reeds afgelost).")

    # Cumulative NCW plot (fixed size, interactive zoom within data range)
    st.subheader("Cumulatieve Net Cash Flow (NCW) over projecthorizon")
    plot_df = cashflow_df[["Year","Free Cash Flow"]].copy()
    plot_df["Cumulative NCW"] = plot_df["Free Cash Flow"].cumsum()

    # Build plotly figure
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=plot_df["Year"].astype(int),
        y=plot_df["Cumulative NCW"],
        mode="lines+markers",
        name="Cumulatieve NCW"
    ))
    fig.update_layout(
        xaxis_title="Jaar",
        yaxis_title="Cumulatieve NCW (" + params.get("currency","EUR") + ")",
        height=450,
        margin=dict(l=60, r=20, t=30, b=60),
    )
    # Fix x-axis range to data range but allow zoom within:
    x_min = int(plot_df["Year"].min())
    x_max = int(plot_df["Year"].max())
    fig.update_xaxes(range=[x_min, x_max], autorange=False)
    # Format y-axis tick labels using European format function via hovertemplate
    fig.update_traces(hovertemplate="%{x}: %{y:.2f}")
    st.plotly_chart(fig, use_container_width=True)

    # -------------------------
    # Scenario saving/export
    # -------------------------
    st.markdown("---")
    st.subheader("Scenario opslaan / exporteren")
    scenario_name = st.text_input("Scenario naam", value=f"{algae_type}_{scale}m3_{start_year}")
    persist = st.checkbox("Persistente opslag (bewaar op schijf)", value=True)
    if st.button("Sla scenario op in sessie"):
        scenario = {
            "name": scenario_name,
            "saved_at": datetime.utcnow().isoformat(),
            "assumptions": {
                "algae_type": algae_type,
                "scale_m3": scale,
                "capex": total_capex,
                "selling_price": selling_price,
                "production_kg": production_fixed,
                "equity_pct": equity_pct,
                "loan_interest": loan_interest,
                "loan_term": loan_term,
                "grace_period": grace_period,
                "contract_type": contract_type,
                "purchase_price": purchase_price if 'purchase_price' in locals() else None,
                "annual_self_generation_kwh": annual_self_generation_kwh,   
            },
            "kpis": {
                "revenue_y1": float(cashflow_df.loc[0,"Revenue"]),
                "total_opex_y1": float(cashflow_df.loc[0,"OPEX"]),
                "net_income_y1": float(cashflow_df.loc[0,"Net Income"]),
                "npv": float(model_npv),
                "irr": float(model_irr) if model_irr is not None else None
            },
            "cashflow": cashflow_df.to_dict(orient="list"),
            "loan": loan_df.to_dict(orient="list")
        }
        st.session_state["scenarios"][scenario_name] = scenario
        if persist:
            safe_name = "".join(c for c in scenario_name if c.isalnum() or c in (" ", "_", "-")).rstrip()
            path = os.path.join(SCENARIO_DIR, f"{safe_name}.json")
            save_json(path, scenario)
        st.success(f"Scenario '{scenario_name}' opgeslagen.")

    # Export current scenario to Excel
    if st.button("Export huidige scenario naar Excel (.xlsx)"):
        summary_df = pd.DataFrame([{
            "Scenario": scenario_name,
            "Algae": algae_type,
            "Scale_m3": scale,
            "CAPEX": total_capex,
            "SellingPrice": selling_price,
            "Production_kg": production_fixed,
            "Revenue_y1": float(cashflow_df.loc[0,"Revenue"]),
            "NetIncome_y1": float(cashflow_df.loc[0,"Net Income"]),
            "NPV": float(model_npv),
            "IRR": float(model_irr) if model_irr is not None else None
        }])
        cf_export = cashflow_df.copy()
        loan_export = loan_df.copy()
        dfs = {"Summary": summary_df, "Cashflow": cf_export, "LoanSchedule": loan_export, "Assumptions": pd.DataFrame([scenario["assumptions"]])}
        xlsx_bytes = write_excel_bytes(dfs)
        st.download_button("Download Excel (.xlsx)", data=xlsx_bytes, file_name=f"{scenario_name}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    if st.button("Export huidige scenario naar CSV (summary)"):
        summary = {
            "Scenario": scenario_name,
            "Algae": algae_type,
            "Scale_m3": scale,
            "CAPEX": total_capex,
            "SellingPrice": selling_price,
            "Production_kg": production_fixed,
            "Revenue_y1": float(cashflow_df.loc[0,"Revenue"]),
            "NetIncome_y1": float(cashflow_df.loc[0,"Net Income"]),
            "NPV": float(model_npv),
            "IRR": float(model_irr) if model_irr is not None else None
        }
        df_csv = pd.DataFrame([summary])
        st.download_button("Download CSV", data=df_csv.to_csv(index=False).encode("utf-8"), file_name=f"{scenario_name}.csv", mime="text/csv")

# -------------------------
# SCENARIOS PAGE
# -------------------------
elif page == "Scenario's":
    st.header("Scenario's")
    scenarios = st.session_state.get("scenarios", {})
    if not scenarios:
        st.info("Geen scenario's gevonden. Maak en sla een scenario op in 'Modelberekening'.")
    else:
        df = pd.DataFrame.from_dict(scenarios, orient="index")
        # show summary table (select key KPI columns)
        summary_rows = []
        for name, sc in scenarios.items():
            k = sc.get("kpis", {})
            summary_rows.append({
                "name": name,
                "algae": sc.get("assumptions",{}).get("algae_type"),
                "scale_m3": sc.get("assumptions",{}).get("scale_m3"),
                "capex": sc.get("assumptions",{}).get("capex"),
                "revenue_y1": k.get("revenue_y1"),
                "net_income_y1": k.get("net_income_y1"),
                "npv": k.get("npv"),
                "irr": k.get("irr")
            })
        summary_df = pd.DataFrame(summary_rows)
        # format currency columns for readability
        for c in ["capex","revenue_y1","net_income_y1","npv"]:
            if c in summary_df.columns:
                summary_df[c] = summary_df[c].apply(lambda x: eur_format(x) if pd.notnull(x) else x)
        if "irr" in summary_df.columns:
            summary_df["irr"] = summary_df["irr"].apply(lambda x: f"{x*100:.2f}%" if pd.notnull(x) else "N/A")
        st.dataframe(summary_df.reset_index(drop=True), use_container_width=True)

        # Manage persistent files
        st.markdown("---")
        st.subheader("Persistent scenario beheer")
        files = [f for f in os.listdir(SCENARIO_DIR) if f.endswith(".json")]
        if files:
            sel = st.selectbox("Laad persistente scenario (van schijf)", options=["--select--"] + files)
            if sel and sel != "--select--":
                if st.button("Importeer geselecteerd in sessie"):
                    sc = load_json(os.path.join(SCENARIO_DIR, sel))
                    if sc and "name" in sc:
                        st.session_state["scenarios"][sc["name"]] = sc
                        st.success(f"Scenario '{sc['name']}' geïmporteerd in sessie.")
        if st.button("Verwijder alle persistente scenario bestanden van schijf"):
            for f in files:
                os.remove(os.path.join(SCENARIO_DIR, f))
            st.success("Alle persistente scenario bestanden verwijderd.")

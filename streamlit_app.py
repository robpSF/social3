import streamlit as st
import pandas as pd
import random
from collections import Counter, defaultdict

# Probability mapping if your Faction file uses "High/Moderate/Low"
PROB_MAP = {
    "High": 0.9,
    "Moderate": 0.5,
    "Low": 0.3,
    "None": 0.0
}

def parse_faction_list(cell_value):
    """Parse a comma-separated list of faction names from the cell."""
    if pd.isna(cell_value) or str(cell_value).strip() == "":
        return []
    return [x.strip() for x in str(cell_value).split(",") if x.strip()]

def main():
    st.title("Option 2 Extended: Celebrity + Faction + Large-Faction Scaling")

    # File uploaders
    faction_file = st.file_uploader("Upload Factions Excel", type=["xlsx","xls"])
    persona_file = st.file_uploader("Upload Personas Excel", type=["xlsx","xls"])

    st.markdown("""
    **Logic**  
    1. **Celebrity probability**:  
       \\[
         p_{\\text{celeb}}(B) = \\alpha * \\frac{B.\\text{TwFollowers}}{\\max(\\text{TwFollowers})}
       \\]
    2. **Faction probability** \\(p_{\\text{faction}}\\), either from:  
       - “High” = 0.9,  
       - “Moderate” = 0.5,  
       - “never” = 0,  
       - or unmentioned => 0.  
       - If same faction, use that row's `intra_prob`.  
    3. **Scale** that probability by \\(1/(\\text{size}(A)^\\beta)\\) so large factions don't overwhelm everyone.  
       \\[
         p_{\\text{faction}}' = \\frac{ p_{\\text{faction}} }{ (\\text{size of faction A})^{\\beta} }
       \\]
    4. **Combine** by **union**:  
       \\[
         p_{\\text{final}} = 1 - (1 - p_{\\text{celeb}})(1 - p_{\\text{faction}}')
       \\]
    5. If “Ignore=1,” skip that faction's personas entirely.
    """)

    alpha = st.slider("Celebrity Weight (alpha)", 0.0, 1.0, 0.5, 0.05,
                     help="Scales how strongly TwFollowers influences following.")
    exponent = st.slider("Faction Size Exponent (beta)", 0.0, 1.0, 0.5, 0.05,
                         help="Larger beta => bigger factions get proportionally reduced more strongly.")
    do_random_draw = st.checkbox("Perform random draw to form actual edges?", value=True)

    if faction_file and persona_file:
        # ------------------------------
        # 1) Read the Excel files
        # ------------------------------
        df_factions = pd.read_excel(faction_file)
        df_personas = pd.read_excel(persona_file)

        st.subheader("Factions Data Preview")
        st.write(df_factions.head())

        st.subheader("Personas Data Preview")
        st.write(df_personas.head())

        # ------------------------------
        # 2) Parse Factions
        # ------------------------------
        faction_info = {}
        for _, row in df_factions.iterrows():
            fac_name = str(row["Faction"]).strip()
            ign_flag = row.get("Ignore", 0)
            ignore_bool = (ign_flag == 1)

            # Intra-faction
            intra_label = str(row.get("IntraFaction Following", "None")).strip()
            intra_p = PROB_MAP.get(intra_label, 0.0)

            # Cross-faction columns
            fHigh   = parse_faction_list(row.get("Factions Following", None))
            fMod    = parse_faction_list(row.get("Factions who may Follow", None))
            fNever  = parse_faction_list(row.get("Factions who’ll never Follow", None))

            faction_info[fac_name] = {
                "ignore": ignore_bool,
                "intra_prob": intra_p,
                "fHigh": fHigh,
                "fMod": fMod,
                "fNever": fNever
            }

        # ------------------------------
        # 3) Parse Personas
        # ------------------------------
        personas = []
        for _, row in df_personas.iterrows():
            handle = str(row["Handle"]).strip()
            name   = str(row.get("Name", handle))
            fac    = str(row["Faction"]).strip()
            tw     = float(row.get("TwFollowers", 0))

            # skip if faction is ignored or not found
            if fac not in faction_info:
                continue
            if faction_info[fac]["ignore"]:
                continue

            personas.append({
                "handle": handle,
                "name": name,
                "faction": fac,
                "tw": tw
            })

        st.write(f"Total personas after ignoring: {len(personas)}")
        if not personas:
            st.stop()

        # Build quick lookups
        handle2name = {p["handle"]: p["name"] for p in personas}
        handle2fac  = {p["handle"]: p["faction"] for p in personas}

        # Group personas by faction, so we know how large each faction is
        from collections import defaultdict
        faction_personas = defaultdict(list)
        for p in personas:
            faction_personas[p["faction"]].append(p)
        faction_sizes = {f: len(lst) for f,lst in faction_personas.items()}

        # max TwFollowers
        max_tw = max(p["tw"] for p in personas) or 1.0

        # ------------------------------
        # Helper: get base faction prob
        # ------------------------------
        def get_faction_prob(fA, fB):
            """Return the 'base' probability that A's faction follows B's faction, ignoring large-faction scaling."""
            if fA == fB:
                # Intra-faction
                return faction_info[fA]["intra_prob"]

            infoB = faction_info[fB]
            if fA in infoB["fNever"]:
                return 0.0
            elif fA in infoB["fHigh"]:
                return 0.9
            elif fA in infoB["fMod"]:
                return 0.5
            else:
                return 0.0

        # ------------------------------
        # 4) Compute final edge probabilities
        # Union of celebrity + faction, with scaling for large factions
        # ------------------------------
        edges_prob = []
        for A in personas:
            for B in personas:
                if A["handle"] == B["handle"]:
                    continue

                # 1) Celebrity prob
                p_celeb = alpha * (B["tw"] / max_tw)

                # 2) Base faction prob
                base_f = get_faction_prob(A["faction"], B["faction"])

                # 3) Scale down if faction A is large
                fac_size = faction_sizes[A["faction"]]
                if fac_size > 1 and base_f > 0 and exponent>0:
                    scale_factor = (fac_size ** exponent)
                    base_f = base_f / scale_factor

                # 4) Union
                p_final = 1 - (1 - p_celeb)*(1 - base_f)

                edges_prob.append({
                    "source": A["handle"],
                    "target": B["handle"],
                    "p_celeb": p_celeb,
                    "p_faction_raw": get_faction_prob(A["faction"], B["faction"]),  # just for debugging
                    "p_faction_scaled": base_f,
                    "p_final": p_final
                })

        # ------------------------------
        # 5) Display + Random Draw
        # ------------------------------
        if do_random_draw:
            chosen_edges = []
            from collections import Counter
            in_counter = Counter()

            for e in edges_prob:
                if random.random() < e["p_final"]:
                    chosen_edges.append(e)
                    in_counter[e["target"]] += 1

            st.write(f"Random-draw edges: {len(chosen_edges)}")

            # Build an in-degree table
            in_deg_table = []
            for p in personas:
                h = p["handle"]
                in_deg_table.append({
                    "handle": h,
                    "name": handle2name[h],
                    "faction": handle2fac[h],
                    "in_degree": in_counter[h]
                })
            df_in_deg = pd.DataFrame(in_deg_table).sort_values("in_degree", ascending=False)
            st.subheader("In-Degree (Actual)")
            st.dataframe(df_in_deg)

            st.write("Showing first 500 edges:")
            st.dataframe(pd.DataFrame(chosen_edges).head(500))

        else:
            st.subheader("Probabilistic Edges (No Random Draw)")
            st.write("Showing first 500 edges:")
            df_prob = pd.DataFrame(edges_prob)
            st.dataframe(df_prob.head(500))

            # Expected in-degree
            in_sum = defaultdict(float)
            for e in edges_prob:
                in_sum[e["target"]] += e["p_final"]
            rows = []
            for p in personas:
                h = p["handle"]
                rows.append({
                    "handle": h,
                    "name": handle2name[h],
                    "faction": handle2fac[h],
                    "expected_in_degree": in_sum[h]
                })
            df_in = pd.DataFrame(rows).sort_values("expected_in_degree", ascending=False)
            st.subheader("Expected In-Degree")
            st.dataframe(df_in)

        # Download option
        st.write("### Download all edges probabilities as CSV")
        csv_data = pd.DataFrame(edges_prob).to_csv(index=False)
        st.download_button(
            "Download Edges CSV",
            data=csv_data,
            file_name="edges_prob.csv",
            mime="text/csv"
        )

if __name__ == "__main__":
    main()

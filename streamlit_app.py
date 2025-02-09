import streamlit as st
import pandas as pd
import random
from collections import Counter, defaultdict

# Hard-coded mappings for IntraFaction or cross-faction “High/Moderate”
PROB_MAP = {
    "High": 0.9,
    "Moderate": 0.5,
    "Low": 0.3,
    "None": 0.0
}

def parse_faction_list(cell_value):
    """Parse comma-separated factions from a cell, or return an empty list if blank."""
    if pd.isna(cell_value) or str(cell_value).strip() == "":
        return []
    return [x.strip() for x in str(cell_value).split(",") if x.strip()]

def main():
    st.title("Option 2: Celebrity + Faction (Union Formula)")

    faction_file = st.file_uploader("Upload Factions Excel", type=["xlsx","xls"])
    persona_file = st.file_uploader("Upload Personas Excel", type=["xlsx","xls"])

    st.write("""
    **Logic**:
    1. Celebrity prob = alpha * (B's TwFollowers / maxTw).
    2. Faction prob = see if A's faction is listed in B's row:
       - never => 0
       - High => 0.9
       - Moderate => 0.5
       - else => 0
    3. Final = 1 - (1 - p_celeb)*(1 - p_faction).
    4. If faction is "ignore=1", skip its personas entirely.
    """)

    alpha = st.slider("Celebrity Weight (alpha)", 0.0, 1.0, 0.5, 0.05)
    randomize = st.checkbox("Random draw to create realized edges?", value=True)

    if faction_file and persona_file:
        df_factions = pd.read_excel(faction_file)
        df_personas = pd.read_excel(persona_file)

        st.subheader("Raw Factions Data")
        st.write(df_factions.head())

        st.subheader("Raw Personas Data")
        st.write(df_personas.head())

        # Parse the Factions
        faction_info = {}
        for _, row in df_factions.iterrows():
            fac_name = str(row["Faction"]).strip()
            ignore_flag = row.get("Ignore", 0)
            ignore_bool = (ignore_flag == 1)

            # Possibly store intrafaction following if you want it
            intra_label = str(row.get("IntraFaction Following", "None")).strip()
            intra_prob = PROB_MAP.get(intra_label, 0.0)

            # Cross-faction columns
            fHigh = parse_faction_list(row.get("Factions Following", None))
            fMod  = parse_faction_list(row.get("Factions who may Follow", None))
            fNever= parse_faction_list(row.get("Factions who’ll never Follow", None))

            faction_info[fac_name] = {
                "ignore": ignore_bool,
                "intra_prob": intra_prob,
                "fHigh": fHigh,
                "fMod": fMod,
                "fNever": fNever
            }

        # Parse Personas
        personas = []
        for _, row in df_personas.iterrows():
            handle = str(row["Handle"]).strip()
            name   = str(row.get("Name", handle))
            fac    = str(row["Faction"]).strip()
            tw     = float(row.get("TwFollowers", 0))

            # Skip if faction not found or faction is ignored
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

        st.write(f"Total personas (after ignoring) = {len(personas)}")
        if not personas:
            st.stop()

        # Quick lookups
        handle2name = {p["handle"]: p["name"] for p in personas}
        handle2faction = {p["handle"]: p["faction"] for p in personas}

        # Max Tw
        max_tw = max(p["tw"] for p in personas) or 1.0

        # Faction prob
        def get_faction_prob(fA, fB):
            """
            Cross-Faction:
             - If fA in fB's "never", => 0
             - If fA in fB's "fHigh", => 0.9
             - If fA in fB's "fMod", => 0.5
             else => 0.0
            Intra-Faction: if fA == fB, could use row's 'intra_prob' or skip it.
            """
            if fA == fB:
                # Intra-faction: for demonstration, let's just return the row's intra_prob
                return faction_info[fA]["intra_prob"]

            infoB = faction_info[fB]
            if fA in infoB["fNever"]:
                # "never follow" B => 0
                return 0.0
            elif fA in infoB["fHigh"]:
                return 0.9
            elif fA in infoB["fMod"]:
                return 0.5
            else:
                return 0.0

        edges_prob = []
        # Build edges with union formula
        for A in personas:
            for B in personas:
                if A["handle"] == B["handle"]:
                    continue

                p_celeb = alpha * (B["tw"] / max_tw)  # celebrity factor
                p_f = get_faction_prob(A["faction"], B["faction"])

                # Union => 1 - (1 - p_celeb)*(1 - p_f)
                # If "never follow" truly trumps celebrity, you can handle that as p_final=0 if p_f=0 for "never."
                p_final = 1 - (1 - p_celeb)*(1 - p_f)

                # If you interpret "never" as absolute zero, you could do:
                #   if A.faction in infoB["fNever"]: p_final = 0

                # clamp
                if p_final < 0:
                    p_final = 0
                elif p_final > 1:
                    p_final = 1

                edges_prob.append({
                    "source": A["handle"],
                    "target": B["handle"],
                    "p_celeb": p_celeb,
                    "p_faction": p_f,
                    "p_final": p_final
                })

        # Show or randomize
        if randomize:
            chosen_edges = []
            in_counter = Counter()
            for e in edges_prob:
                if random.random() < e["p_final"]:
                    chosen_edges.append(e)
                    in_counter[e["target"]] += 1

            st.write(f"Total edges after random draw: {len(chosen_edges)}")

            # In-degree table
            in_deg_list = []
            for p in personas:
                h = p["handle"]
                in_deg = in_counter[h]
                in_deg_list.append({
                    "handle": h,
                    "name": handle2name[h],
                    "faction": handle2faction[h],
                    "in_degree": in_deg
                })
            df_in_deg = pd.DataFrame(in_deg_list).sort_values("in_degree", ascending=False)
            st.subheader("In-degree (Actual)")
            st.dataframe(df_in_deg)

            st.write("Showing up to first 500 edges:")
            st.dataframe(pd.DataFrame(chosen_edges).head(500))

        else:
            st.subheader("Edges with Probability (No Random Draw)")
            st.write("Showing up to first 500 edges:")
            df_edges = pd.DataFrame(edges_prob)
            st.dataframe(df_edges.head(500))

            # Expected in-degree
            in_sum = defaultdict(float)
            for e in edges_prob:
                in_sum[e["target"]] += e["p_final"]
            in_deg_list = []
            for p in personas:
                h = p["handle"]
                in_deg_list.append({
                    "handle": h,
                    "name": handle2name[h],
                    "faction": handle2faction[h],
                    "expected_in_degree": in_sum[h]
                })
            df_in_deg = pd.DataFrame(in_deg_list).sort_values("expected_in_degree", ascending=False)
            st.subheader("Expected In-Degree")
            st.dataframe(df_in_deg)

        # Optionally let user download
        csv_data = pd.DataFrame(edges_prob).to_csv(index=False)
        st.download_button(
            "Download Edge Probabilities CSV",
            data=csv_data,
            file_name="edge_probabilities.csv",
            mime="text/csv"
        )

if __name__ == "__main__":
    main()

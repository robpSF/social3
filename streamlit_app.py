import streamlit as st
import pandas as pd
import numpy as np
import random
from collections import defaultdict, Counter

# Master Probability Mapping
PROB_MAP = {
    "High": 0.9,
    "Moderate": 0.5,
    "Low": 0.3,
    "None": 0.0
}

def parse_faction_list(cell_value):
    """Parse a comma-separated string of faction names into a list."""
    if pd.isna(cell_value) or str(cell_value).strip() == "":
        return []
    return [x.strip() for x in str(cell_value).split(",") if x.strip()]

def main():
    st.title("Faction + Personas Social Graph with Scaled Intra-Faction Probability")

    # File uploaders
    faction_file = st.file_uploader("Upload Factions Excel", type=["xlsx","xls"])
    persona_file = st.file_uploader("Upload Personas Excel", type=["xlsx","xls"])

    # This slider lets you choose how strongly to scale down large factions.
    # We’ll do:  p_intra_effective = p_intra / (N^scaling_exponent).
    # E.g. if exponent=0.5 => p_intra / sqrt(N).
    scaling_exponent = st.slider(
        "Intra-Faction Scaling Exponent (0 = no scaling, 0.5 = sqrt, etc.)",
        min_value=0.0, max_value=1.0, value=0.5, step=0.1
    )

    if faction_file and persona_file:
        df_factions = pd.read_excel(faction_file)
        df_personas = pd.read_excel(persona_file)

        st.subheader("Raw Factions Data")
        st.write(df_factions.head())

        st.subheader("Raw Personas Data")
        st.write(df_personas.head())

        # -------------------------
        # Parse Factions
        # -------------------------
        faction_info = {}
        for _, row in df_factions.iterrows():
            # Make sure the column is named "Faction" in your file
            faction_name = str(row["Faction"]).strip()
            ignore_flag = row.get("Ignore", 0)
            ignore_bool = (ignore_flag == 1)

            intra_label = str(row.get("IntraFaction Following", "None")).strip()
            p_intra = PROB_MAP.get(intra_label, 0.0)

            fHigh   = parse_faction_list(row.get("Factions Following", None))
            fMod    = parse_faction_list(row.get("Factions who may Follow", None))
            fNever  = parse_faction_list(row.get("Factions who’ll never Follow", None))

            faction_info[faction_name] = {
                "ignore": ignore_bool,
                "intra_prob": p_intra,
                "fHigh": fHigh,
                "fMod":  fMod,
                "fNever": fNever
            }

        # -------------------------
        # Parse Personas
        # -------------------------
        personas = []
        for _, row in df_personas.iterrows():
            handle  = str(row["Handle"]).strip()   # unique ID
            name    = str(row.get("Name", handle))
            fac     = str(row["Faction"]).strip()
            tw      = row.get("TwFollowers", 0)

            if fac not in faction_info:
                continue
            if faction_info[fac]["ignore"]:
                continue

            personas.append({
                "handle": handle,
                "name": name,
                "faction": fac,
                "tw": float(tw)
            })

        st.write(f"Total personas (after ignoring factions) = {len(personas)}")
        if not personas:
            st.warning("No personas found. Check your Factions 'Ignore' column or file alignment.")
            return

        # Group personas by faction to know how many are in each
        from collections import defaultdict
        faction_personas = defaultdict(list)
        for p in personas:
            faction_personas[p["faction"]].append(p)

        # We'll need the sizes:
        faction_sizes = {f: len(p_list) for f, p_list in faction_personas.items()}

        # The max TwFollowers among included personas
        max_tw = max(p["tw"] for p in personas) or 1.0

        # -------------------------
        # Faction Probability Helper
        # -------------------------
        def get_faction_prob(factionA, factionB):
            """Return the 'base' faction-based probability for A->B, ignoring popularity scaling."""
            # Intra-Faction logic (scaled down for large factions)
            if factionA == factionB:
                base_p = faction_info[factionA]["intra_prob"]
                n = faction_sizes[factionA]
                if n > 1 and base_p > 0:
                    # scale by 1/(n^exponent)
                    scale_factor = n ** scaling_exponent
                    base_p = base_p / scale_factor
                return base_p

            # Cross-faction logic: see if factionA is in factionB's list
            infoB = faction_info[factionB]
            if factionA in infoB["fNever"]:
                return 0.0
            elif factionA in infoB["fHigh"]:
                return 0.9
            elif factionA in infoB["fMod"]:
                return 0.5
            else:
                # If silent => 0.0 (or you could pick 0.3 as a fallback)
                return 0.0

        # -------------------------
        # Build edges with probabilities
        # Union-based formula with popularity
        # -------------------------
        edges_prob = []
        for personaA in personas:
            for personaB in personas:
                if personaA["handle"] == personaB["handle"]:
                    continue

                facA = personaA["faction"]
                facB = personaB["faction"]

                base_p = get_faction_prob(facA, facB)

                if base_p == 0.0:
                    p_final = 0.0
                else:
                    ratioB = personaB["tw"] / max_tw
                    # Union-based formula
                    p_final = 1 - (1 - base_p)*(1 - ratioB)

                edges_prob.append({
                    "source": personaA["handle"],
                    "target": personaB["handle"],
                    "p_final": p_final
                })

        # -------------------------
        # Let user pick whether to randomize
        # -------------------------
        st.write("### Edge Probability Results")
        randomize = st.checkbox("Generate a realized following network (random draw)?", value=False)

        if randomize:
            # We'll create a list of only edges that "exist" after random draw
            edges_drawn = []
            for e in edges_prob:
                if random.random() < e["p_final"]:
                    edges_drawn.append(e)

            st.write(f"Total edges after random draw: {len(edges_drawn)}")

            # Compute actual in-degree
            from collections import Counter
            in_counter = Counter()
            for e in edges_drawn:
                in_counter[e["target"]] += 1

            handle2name = {p["handle"]: p["name"] for p in personas}
            indegree_list = []
            for p in personas:
                h = p["handle"]
                indeg = in_counter[h]
                indegree_list.append({
                    "handle": h,
                    "name": p["name"],
                    "in_degree": indeg
                })
            df_indegree = pd.DataFrame(indegree_list).sort_values("in_degree", ascending=False)

            st.subheader("In-Degree (Actual) from Realized Network")
            st.dataframe(df_indegree)

            st.write("Showing up to first 500 realized edges:")
            st.dataframe(pd.DataFrame(edges_drawn).head(500))

        else:
            # Expected in-degree = sum of probabilities on incoming edges
            incoming_prob_sum = defaultdict(float)
            for e in edges_prob:
                incoming_prob_sum[e["target"]] += e["p_final"]

            handle2name = {p["handle"]: p["name"] for p in personas}
            indegree_list = []
            for p in personas:
                h = p["handle"]
                indeg = incoming_prob_sum[h]
                indegree_list.append({
                    "handle": h,
                    "name": handle2name[h],
                    "expected_in_degree": indeg
                })
            df_expected_in = pd.DataFrame(indegree_list).sort_values("expected_in_degree", ascending=False)

            st.subheader("In-Degree (Expected)")
            st.dataframe(df_expected_in)

            st.write("Showing up to first 500 edges (p_final).")
            st.dataframe(pd.DataFrame(edges_prob).head(500))

        # Optional download of entire edge probability set
        st.write("### Download Edge Data")
        csv_edges = pd.DataFrame(edges_prob).to_csv(index=False)
        st.download_button(
            label="Download edge probabilities CSV",
            data=csv_edges,
            file_name="edges_probability.csv",
            mime="text/csv"
        )

if __name__ == "__main__":
    main()

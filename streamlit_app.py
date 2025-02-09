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
    st.title("Faction + Personas Social Graph Demo")

    # File uploaders
    faction_file = st.file_uploader("Upload Factions Excel", type=["xlsx","xls"])
    persona_file = st.file_uploader("Upload Personas Excel", type=["xlsx","xls"])

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
            # Make sure the column is actually named "Faction" in your Excel
            faction_name = str(row["Faction"]).strip()
            ignore_flag = row.get("Ignore", 0)
            ignore_bool = (ignore_flag == 1)

            intra_label = str(row.get("IntraFaction Following", "None")).strip()
            p_intra = PROB_MAP.get(intra_label, 0.0)

            fHigh = parse_faction_list(row.get("Factions Following", None))
            fMod  = parse_faction_list(row.get("Factions who may Follow", None))
            fNever= parse_faction_list(row.get("Factions who’ll never Follow", None))

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

        max_tw = max(p["tw"] for p in personas) or 1.0

        # Index of faction -> list of persona dicts
        faction_personas = defaultdict(list)
        for p in personas:
            faction_personas[p["faction"]].append(p)

        # Function to get base probability that A->B due to faction logic
        def get_faction_prob(factionA, factionB):
            if factionA == factionB:
                return faction_info[factionA]["intra_prob"]
            infoB = faction_info[factionB]
            if factionA in infoB["fNever"]:
                return 0.0
            elif factionA in infoB["fHigh"]:
                return 0.9
            elif factionA in infoB["fMod"]:
                return 0.5
            else:
                # If silent => 0.0 or 0.3 as fallback
                return 0.0

        # -------------------------
        # Build edges with probabilities
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
                    p_final = 1 - (1 - base_p)*(1 - ratioB)

                edges_prob.append({
                    "source": personaA["handle"],
                    "target": personaB["handle"],
                    "p_final": p_final
                })

        st.write("### Edge Probability Results")

        # Let user decide to randomize or keep probabilities
        randomize = st.checkbox("Generate a realized following network (random draw)?", value=False)

        if randomize:
            # Do random draw
            edges_drawn = []
            for e in edges_prob:
                if random.random() < e["p_final"]:
                    edges_drawn.append(e)  # or store e with an "exists"=1

            st.write(f"Total edges after random draw: {len(edges_drawn)}")

            # -------------------------
            # Compute in-degree (actual)
            # -------------------------
            in_counter = Counter()
            for e in edges_drawn:
                in_counter[e["target"]] += 1

            # Create a DataFrame for in-degree
            # We'll also map the handle to the persona name
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

            # Also show edges if wanted
            st.write("Showing up to first 500 realized edges:")
            st.dataframe(pd.DataFrame(edges_drawn).head(500))

        else:
            # No random draw => we have p_final for each edge
            # We'll treat "in-degree" as the sum of probabilities of incoming edges
            # i.e. "expected" in-degree
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
                    "name": p["name"],
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

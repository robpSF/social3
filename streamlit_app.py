import streamlit as st
import pandas as pd
import numpy as np
import random

# ---------------------------------------
# 1. Master Probability Mapping
# ---------------------------------------
PROB_MAP = {
    "High": 0.9,
    "Moderate": 0.5,
    "Low": 0.3,
    "None": 0.0  # or call it "Never" if you'd like
}

# ---------------------------------------
# Helper to parse faction-list columns
# e.g. "Iraqi Public, Jordanian Public" -> ["Iraqi Public","Jordanian Public"]
# ---------------------------------------
def parse_faction_list(cell_value):
    if pd.isna(cell_value) or str(cell_value).strip() == "":
        return []
    # split on commas
    return [x.strip() for x in str(cell_value).split(",") if x.strip()]

def main():
    st.title("Faction + Personas Social Graph Demo")

    # ---------------------------------------
    # 2. File Uploaders for Factions and Personas
    # ---------------------------------------
    faction_file = st.file_uploader("Upload Factions Excel", type=["xlsx", "xls"])
    persona_file = st.file_uploader("Upload Personas Excel", type=["xlsx", "xls"])

    if faction_file and persona_file:
        # ---------------------------------------
        # 3. Read the Data
        # ---------------------------------------
        df_factions = pd.read_excel(faction_file)
        df_personas = pd.read_excel(persona_file)

        st.subheader("Raw Factions Data")
        st.write(df_factions.head())

        st.subheader("Raw Personas Data")
        st.write(df_personas.head())

        # ---------------------------------------
        # 3a. Parse Factions
        # ---------------------------------------
        # We'll build a dict like:
        # faction_info = {
        #   "FactionName": {
        #       "ignore": True/False,
        #       "intra_prob": float,
        #       "fHigh": [...],
        #       "fMod": [...],
        #       "fNever": [...]
        #   },
        #   ...
        # }
        faction_info = {}
        for _, row in df_factions.iterrows():
            f_name = str(row["Faction"]).strip()
            ignore_flag = row.get("Ignore", 0)
            ignore_bool = (ignore_flag == 1)

            # map the IntraFaction Following text to numeric
            intra_label = str(row.get("IntraFaction Following", "None")).strip()
            # default to 0 if not in PROB_MAP
            p_intra = PROB_MAP.get(intra_label, 0.0)

            # parse "Factions Following", "Factions who may Follow", "Factions who’ll never Follow"
            fHigh = parse_faction_list(row.get("Factions Following", None))
            fMod  = parse_faction_list(row.get("Factions who may Follow", None))
            fNever= parse_faction_list(row.get("Factions who’ll never Follow", None))

            faction_info[f_name] = {
                "ignore": ignore_bool,
                "intra_prob": p_intra,
                "fHigh": fHigh,
                "fMod":  fMod,
                "fNever": fNever
            }

        # ---------------------------------------
        # 3b. Parse Personas
        # ---------------------------------------
        # We'll store a list of included personas, each a dict with
        # { "handle": ..., "name": ..., "faction": ..., "tw": ... }
        # also group them by faction if we want
        personas = []
        for _, row in df_personas.iterrows():
            handle  = str(row["Handle"]).strip()   # unique ID
            name    = str(row.get("Name", handle))
            faction = str(row["Faction"]).strip()
            tw      = row.get("TwFollowers", 0)

            # if faction not in faction_info or ignored, skip
            if faction not in faction_info:
                continue
            if faction_info[faction]["ignore"]:
                continue

            personas.append({
                "handle": handle,
                "name": name,
                "faction": faction,
                "tw": float(tw)
            })

        st.write(f"Total personas (after ignoring factions) = {len(personas)}")

        # if no personas, exit early
        if len(personas) == 0:
            st.warning("No personas found after filtering out ignored factions.")
            return

        # ---------------------------------------
        # 4. Find max TwFollowers
        # ---------------------------------------
        max_tw = max(p["tw"] for p in personas)
        if max_tw == 0:
            max_tw = 1.0  # avoid divide-by-zero if all are 0

        # ---------------------------------------
        # 5. Compute Edge Probabilities
        # We'll produce a list of edges: (source, target, p_final)
        # Where source/target = persona.handle
        # ---------------------------------------
        edges_prob = []

        # Build a quick index of faction -> list of persona dicts
        from collections import defaultdict
        faction_personas = defaultdict(list)
        for p in personas:
            faction_personas[p["faction"]].append(p)

        # Helper: get base probability that "factionA" follows "factionB"
        # from the perspective "A -> B", but the row is B in the table,
        # which says who follows B.  We'll check if factionA is in B's 'fHigh','fMod','fNever'
        def get_faction_prob(factionA, factionB):
            # If same faction, use B's intra_faction_prob. Actually we want
            # the same faction's row for that. But let's keep it simpler:
            # "intra_faction_prob" is the same for A & B in that faction, so let's pick either row.
            if factionA == factionB:
                return faction_info[factionA]["intra_prob"]

            # otherwise, see if factionA is in factionB's list
            # Because "Factions Following" = who follows factionB at High
            infoB = faction_info[factionB]
            if factionA in infoB["fNever"]:
                return 0.0
            elif factionA in infoB["fHigh"]:
                return 0.9
            elif factionA in infoB["fMod"]:
                return 0.5
            else:
                # If silent => assume 0.0 (or pick 0.3 if you want a fallback)
                return 0.0

        # Now create edges
        for personaA in personas:
            for personaB in personas:
                if personaA["handle"] == personaB["handle"]:
                    continue  # no self-edges

                facA = personaA["faction"]
                facB = personaB["faction"]

                base_p = get_faction_prob(facA, facB)
                if base_p == 0.0:
                    # "never follow" scenario or no match => final prob = 0
                    p_final = 0.0
                else:
                    ratioB = personaB["tw"] / max_tw
                    # union-based formula
                    # p_final = 1 - (1 - base_p)*(1 - ratioB)
                    p_final = 1 - (1 - base_p) * (1 - ratioB)

                edges_prob.append({
                    "source": personaA["handle"],
                    "target": personaB["handle"],
                    "p_final": p_final
                })

        # ---------------------------------------
        # 6. Let user pick whether to randomize
        # ---------------------------------------
        st.write("### Edge Probability Results")
        randomize = st.checkbox("Generate a realized following network (random draw)?", value=False)

        if randomize:
            # We'll create a list of only edges that "exist" after random draw
            edges_drawn = []
            for e in edges_prob:
                if random.random() < e["p_final"]:
                    edges_drawn.append({
                        "source": e["source"],
                        "target": e["target"],
                        "exists": 1
                    })
            st.write(f"Total edges after random draw: {len(edges_drawn)}")
            st.dataframe(pd.DataFrame(edges_drawn))
        else:
            # Show probability
            st.write("Showing up to first 500 edges (for brevity).")
            df_edges = pd.DataFrame(edges_prob)
            st.dataframe(df_edges.head(500))

        # Optional: you could let user download the edge list
        csv_edges = pd.DataFrame(edges_prob).to_csv(index=False)
        st.download_button(
            label="Download edge probabilities CSV",
            data=csv_edges,
            file_name="edges_probability.csv",
            mime="text/csv"
        )


if __name__ == "__main__":
    main()

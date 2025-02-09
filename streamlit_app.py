import streamlit as st
import pandas as pd
import numpy as np
import random
from collections import defaultdict, Counter

PROB_MAP = {
    "High": 0.9,
    "Moderate": 0.5,
    "Low": 0.3,
    "None": 0.0
}

def parse_faction_list(cell_value):
    if pd.isna(cell_value) or str(cell_value).strip() == "":
        return []
    return [x.strip() for x in str(cell_value).split(",") if x.strip()]

def main():
    st.title("No-One-Left-Behind Model (with Faction in In-Degree Table)")

    faction_file = st.file_uploader("Upload Factions Excel", type=["xlsx","xls"])
    persona_file = st.file_uploader("Upload Personas Excel", type=["xlsx","xls"])

    st.write("""
    **Approach**:
    - Compute p_final = min(1, p_faction * (ratio_B + alpha)).
    - Randomly pick edges.
    - Post-process so everyone has >=1 follower if possible.
    """)

    scaling_exponent = st.slider("Intra-Faction Scaling Exponent", 0.0, 1.0, 0.5, 0.1)
    alpha = st.slider("Popularity Offset (alpha)", 0.0, 1.0, 0.2, 0.05)

    randomize = st.checkbox("Generate a realized network with 'no one left behind' fix?", True)

    if faction_file and persona_file:
        df_factions = pd.read_excel(faction_file)
        df_personas = pd.read_excel(persona_file)

        st.subheader("Raw Factions Data")
        st.write(df_factions.head())

        st.subheader("Raw Personas Data")
        st.write(df_personas.head())

        # --- Parse Factions ---
        faction_info = {}
        for _, row in df_factions.iterrows():
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

        # --- Parse Personas ---
        personas = []
        for _, row in df_personas.iterrows():
            handle  = str(row["Handle"]).strip()
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
            return

        from collections import defaultdict
        faction_personas = defaultdict(list)
        for p in personas:
            faction_personas[p["faction"]].append(p)

        # We'll need the faction sizes to scale intra-faction prob
        faction_sizes = {f: len(lst) for f, lst in faction_personas.items()}

        max_tw = max(p["tw"] for p in personas) or 1.0

        # Build quick lookup for name/faction
        handle2name = {p["handle"]: p["name"] for p in personas}
        handle2faction = {p["handle"]: p["faction"] for p in personas}

        def get_faction_prob(fA, fB):
            # same faction => scale by 1/(N^exponent)
            if fA == fB:
                base_p = faction_info[fA]["intra_prob"]
                n = faction_sizes[fA]
                if n>1 and base_p>0:
                    scale_factor = n ** scaling_exponent
                    base_p = base_p / scale_factor
                return base_p
            # cross-faction
            infoB = faction_info[fB]
            if fA in infoB["fNever"]:
                return 0.0
            elif fA in infoB["fHigh"]:
                return 0.9
            elif fA in infoB["fMod"]:
                return 0.5
            else:
                return 0.0

        edges = []
        potential_followers_for = defaultdict(list)

        # Calculate p_final
        for A in personas:
            for B in personas:
                if A["handle"] == B["handle"]:
                    continue

                base_p = get_faction_prob(A["faction"], B["faction"])
                if base_p <= 0:
                    p_final = 0.0
                else:
                    ratioB = B["tw"]/max_tw
                    raw_val = base_p*(ratioB + alpha)
                    p_final = min(1.0, raw_val)

                if p_final>0:
                    potential_followers_for[B["handle"]].append((A["handle"], p_final))

                edges.append({
                    "source": A["handle"],
                    "target": B["handle"],
                    "p_final": p_final
                })

        if not randomize:
            st.subheader("Showing Edge Probabilities Only (No Random Draw)")
            df_edges = pd.DataFrame(edges)
            st.dataframe(df_edges.head(500))

            # Expected in-degree
            in_prob_sum = defaultdict(float)
            for e in edges:
                in_prob_sum[e["target"]] += e["p_final"]
            indeg_list = []
            for p in personas:
                h = p["handle"]
                indeg_list.append({
                    "handle": h,
                    "name": handle2name[h],
                    "faction": handle2faction[h],  # <---- ADD FACTION HERE
                    "expected_in_degree": in_prob_sum[h]
                })
            df_in = pd.DataFrame(indeg_list).sort_values("expected_in_degree", ascending=False)
            st.subheader("Expected In-Degree Ranking")
            st.dataframe(df_in)

        else:
            # 1) random draw
            chosen_edges = []
            in_counter = Counter()
            for e in edges:
                if e["p_final"]>0 and random.random()< e["p_final"]:
                    chosen_edges.append(e)
                    in_counter[e["target"]] += 1

            # 2) fix zero in-degree
            forced_edges = []
            for p in personas:
                targ = p["handle"]
                if in_counter[targ] == 0:
                    candidates = potential_followers_for[targ]
                    if candidates:
                        Ahandle, p_val = random.choice(candidates)
                        exists = any((ce["source"]==Ahandle and ce["target"]==targ) for ce in chosen_edges)
                        if not exists:
                            new_edge = {
                                "source": Ahandle,
                                "target": targ,
                                "p_final": p_val,
                                "forced": True
                            }
                            chosen_edges.append(new_edge)
                            in_counter[targ]+=1
                            forced_edges.append(new_edge)

            st.write(f"Total edges after random draw: {len(chosen_edges)}")
            if forced_edges:
                st.write(f"({len(forced_edges)}) edges forcibly added so nobody is left at zero in-degree.")

            # Final in-degree table (actual)
            final_in_deg = []
            for p in personas:
                h = p["handle"]
                final_in_deg.append({
                    "handle": h,
                    "name": handle2name[h],
                    "faction": handle2faction[h],  # <---- ADD FACTION HERE
                    "in_degree": in_counter[h]
                })
            df_in_deg = pd.DataFrame(final_in_deg).sort_values("in_degree", ascending=False)
            st.subheader("In-Degree (Actual) with No-One-Left-Behind Fix")
            st.dataframe(df_in_deg)

            st.write("Up to first 500 chosen edges:")
            st.dataframe(pd.DataFrame(chosen_edges).head(500))

        st.write("### Download Edge Probability Data")
        df_all = pd.DataFrame(edges)
        csv_edges = df_all.to_csv(index=False)
        st.download_button(
            label="Download edge probabilities CSV",
            data=csv_edges,
            file_name="edges_probability.csv",
            mime="text/csv"
        )

if __name__ == "__main__":
    main()

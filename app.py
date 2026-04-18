import streamlit as st
import anthropic
import requests
import json
import os
from dotenv import load_dotenv
from datetime import date, timedelta

load_dotenv()

# ── Config ──────────────────────────────────────────────────────────────────
ANTHROPIC_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
AIRTABLE_TOKEN  = os.getenv("AIRTABLE_TOKEN", "")
AIRTABLE_BASE   = os.getenv("AIRTABLE_BASE_ID", "app8eWcW7BHJ4EGxv")
JINA_KEY        = os.getenv("JINA_API_KEY", "")

AIRTABLE_HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_TOKEN}",
    "Content-Type": "application/json"
}

DAYS = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
MEAL_TYPES = ["Breakfast","Lunch","Dinner","Snack"]
GROCERY_CATS = ["Produce","Proteins","Dairy","Grains","Frozen","Other"]

# ── Airtable helpers ─────────────────────────────────────────────────────────
def at_get(table):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{requests.utils.quote(table)}"
    rows, offset = [], None
    while True:
        params = {"offset": offset} if offset else {}
        r = requests.get(url, headers=AIRTABLE_HEADERS, params=params)
        data = r.json()
        rows += data.get("records", [])
        offset = data.get("offset")
        if not offset:
            break
    return rows

def at_post(table, fields):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{requests.utils.quote(table)}"
    r = requests.post(url, headers=AIRTABLE_HEADERS, json={"records":[{"fields": fields}]})
    return r.json()

def at_post_many(table, records):
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{requests.utils.quote(table)}"
    # Airtable max 10 per request
    for i in range(0, len(records), 10):
        batch = [{"fields": r} for r in records[i:i+10]]
        requests.post(url, headers=AIRTABLE_HEADERS, json={"records": batch})

def at_delete_all(table):
    rows = at_get(table)
    if not rows:
        return
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/{requests.utils.quote(table)}"
    ids = [r["id"] for r in rows]
    for i in range(0, len(ids), 10):
        params = "&".join([f"records[]={rid}" for rid in ids[i:i+10]])
        requests.delete(f"{url}?{params}", headers=AIRTABLE_HEADERS)

def get_recipes():
    rows = at_get("Recipes")
    return [{"id": r["id"], **r["fields"]} for r in rows]

def get_profile():
    rows = at_get("Profiles")
    if rows:
        return rows[0]["fields"]
    return {}

def save_profile(fields):
    rows = at_get("Profiles")
    if rows:
        rid = rows[0]["id"]
        url = f"https://api.airtable.com/v0/{AIRTABLE_BASE}/Profiles/{rid}"
        requests.patch(url, headers=AIRTABLE_HEADERS, json={"fields": fields})
    else:
        at_post("Profiles", fields)

# ── Scraping & parsing ───────────────────────────────────────────────────────
def scrape_url(url):
    """Use Jina.ai to scrape a URL into clean text."""
    if not JINA_KEY:
        return None, "Jina API key not set — paste recipe text instead."
    headers = {"Authorization": f"Bearer {JINA_KEY}", "Accept": "application/json"}
    r = requests.get(f"https://r.jina.ai/{url}", headers=headers, timeout=20)
    if r.status_code == 200:
        data = r.json()
        return data.get("data", {}).get("content", ""), None
    return None, f"Could not scrape URL (status {r.status_code})."

def parse_recipe_with_claude(content, name_hint=""):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    system = """You are a recipe parser. Extract the recipe and return ONLY valid JSON, no markdown, no backticks:
{
  "Name": "Recipe name",
  "Servings": 4,
  "Meal Type": ["Dinner"],
  "Source URL": "",
  "Calories": 450,
  "Protein g": 35,
  "Carbs g": 40,
  "Fat g": 12,
  "Fiber g": 5,
  "Ingredients": "Full ingredient list as text",
  "Instructions": "Step by step instructions as text",
  "Est Cost Per Serving": 4.50,
  "Tags": ["high-protein", "quick"],
  "Notes": ""
}
Meal Type must be an array containing one or more of: Breakfast, Lunch, Dinner, Snack.
Estimate macros and cost per serving as accurately as possible."""

    user = f"Parse this recipe{(' — name hint: ' + name_hint) if name_hint else ''}:\n\n{content}"
    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        system=system,
        messages=[{"role":"user","content":user}]
    )
    text = msg.content[0].text.strip()
    return json.loads(text)

def generate_plan_with_claude(recipes, profile):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    recipe_list = "\n".join([
        f"- {r.get('Name','?')} ({'/'.join(r.get('Meal Type',[]))}): "
        f"{r.get('Calories','?')}cal, {r.get('Protein g','?')}g protein, "
        f"{r.get('Carbs g','?')}g carbs, {r.get('Fat g','?')}g fat, "
        f"~${r.get('Est Cost Per Serving','?')}/serving"
        for r in recipes
    ])
    meals = profile.get("Meals to Plan", "Breakfast, Lunch, Dinner, Snack")
    prompt = f"""Create a 7-day meal plan with these requirements:
Daily targets: {profile.get('Calories Target',2000)} cal, {profile.get('Protein Target',150)}g protein, {profile.get('Carbs Target',200)}g carbs, {profile.get('Fat Target',65)}g fat, {profile.get('Fiber Target',30)}g fiber
Weekly budget: ${profile.get('Weekly Budget',100)}
Meals: {meals}
Meal prep days/week: {profile.get('Meal Prep Days',2)}
Dietary restrictions: {profile.get('Dietary Restrictions','none')}
Servings per household: {profile.get('Servings Per Household',1)}
Notes: {profile.get('Notes','')}

Available recipes:
{recipe_list}

You may suggest simple meals not in the list if needed to hit macro targets.

Return ONLY valid JSON, no markdown:
{{
  "days": [
    {{
      "day": "Monday",
      "meals": [
        {{"type": "Breakfast", "recipe": "Oatmeal with berries", "calories": 380, "protein": 14, "carbs": 68, "fat": 8, "notes": ""}},
        {{"type": "Lunch", "recipe": "...", "calories": 0, "protein": 0, "carbs": 0, "fat": 0, "notes": ""}},
        {{"type": "Dinner", "recipe": "...", "calories": 0, "protein": 0, "carbs": 0, "fat": 0, "notes": ""}},
        {{"type": "Snack", "recipe": "...", "calories": 0, "protein": 0, "carbs": 0, "fat": 0, "notes": ""}}
      ]
    }}
  ],
  "avg_daily_macros": {{"calories": 2000, "protein": 150, "carbs": 200, "fat": 65}},
  "estimated_weekly_cost": 85,
  "prep_guide": "On Sunday prep X, on Wednesday prep Y...",
  "grocery_list": [
    {{"category": "Produce", "ingredient": "Spinach", "amount": "1 bag", "cost": 3.50}},
    {{"category": "Proteins", "ingredient": "Chicken breast", "amount": "2 lbs", "cost": 8.00}}
  ]
}}"""

    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role":"user","content":prompt}]
    )
    text = msg.content[0].text.strip()
    return json.loads(text)

# ── UI ───────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Macro Meal Planner", page_icon="🥗", layout="wide")

st.markdown("""
<style>
    [data-testid="stSidebar"] { background: #1A1714; }
    [data-testid="stSidebar"] * { color: #FAF7F2 !important; }
    [data-testid="stSidebar"] .stRadio label { color: #FAF7F2 !important; }
    h1 { font-size: 2rem !important; }
    .metric-card { background: white; border: 1px solid #eee; border-radius: 10px; padding: 1rem; text-align: center; }
    .metric-label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: #888; margin-bottom: 4px; }
    .metric-value { font-size: 1.75rem; font-weight: 600; color: #1A1714; }
    .recipe-card { background: white; border: 1px solid #eee; border-radius: 10px; padding: 1rem; margin-bottom: 0.75rem; }
    .day-header { background: #1A1714; color: white; padding: 6px 10px; border-radius: 6px 6px 0 0; font-size: 0.8rem; font-weight: 600; text-align: center; }
    .meal-slot { border: 1px solid #eee; border-top: none; padding: 8px 10px; font-size: 0.8rem; }
    .meal-slot:last-child { border-radius: 0 0 6px 6px; }
    .meal-type { font-size: 0.65rem; text-transform: uppercase; color: #888; font-weight: 600; margin-bottom: 2px; }
</style>
""", unsafe_allow_html=True)

# Sidebar nav
with st.sidebar:
    st.markdown("### 🥗 Macro Meal Planner")
    st.markdown("---")
    page = st.radio("", ["📚 Recipe Library", "⚙️ My Profile", "📅 Weekly Plan", "🛒 Grocery List"], label_visibility="collapsed")

# ── PAGE: Recipe Library ─────────────────────────────────────────────────────
if page == "📚 Recipe Library":
    st.title("Recipe Library")
    st.caption("Add recipes from a URL, pasted text, or an Instagram caption.")

    if not ANTHROPIC_KEY:
        st.error("Anthropic API key not set. Add it to your .env file.")
        st.stop()

    tab1, tab2 = st.tabs(["➕ Add Recipe", "📖 Saved Recipes"])

    with tab1:
        input_type = st.radio("How are you adding this recipe?", ["🔗 URL", "📋 Paste text", "📸 Instagram caption"], horizontal=True)
        name_hint = st.text_input("Recipe name (optional — AI will detect)", placeholder="e.g. Mom's chicken tortilla soup")

        content = None
        source_url = ""

        if input_type == "🔗 URL":
            url = st.text_input("Recipe URL", placeholder="https://www.allrecipes.com/recipe/...")
            if url:
                source_url = url
                if not JINA_KEY:
                    st.warning("Jina API key not set yet. Paste the recipe text instead, or add your Jina key to .env.")
                else:
                    if st.button("Fetch & parse recipe", type="primary"):
                        with st.spinner("Scraping page..."):
                            content, err = scrape_url(url)
                            if err:
                                st.error(err)
                                content = None

        elif input_type == "📋 Paste text":
            content_raw = st.text_area("Paste the full recipe here", height=200,
                placeholder="Ingredients, instructions, anything you have...")
            if content_raw:
                content = content_raw
            if st.button("Parse & save recipe", type="primary") and not content:
                st.warning("Please paste some recipe text first.")

        elif input_type == "📸 Instagram caption":
            st.info("Instagram blocks direct access, but the caption usually has the full recipe. Copy it from the post and paste below.")
            ig_url = st.text_input("Instagram post URL (for reference)", placeholder="https://www.instagram.com/p/...")
            caption = st.text_area("Paste the caption / recipe text here", height=200)
            if ig_url:
                source_url = ig_url
            if caption:
                content = caption
            if st.button("Parse & save recipe", type="primary") and not content:
                st.warning("Please paste the caption text first.")

        # Parse button for text/instagram (URL has its own button above)
        parse_clicked = False
        if input_type != "🔗 URL":
            parse_clicked = st.session_state.get("_parse_clicked", False)
            if st.button("Parse & save recipe", type="primary", key="parse_btn_main"):
                parse_clicked = True

        if content and (parse_clicked or input_type == "🔗 URL"):
            with st.spinner("Claude is parsing the recipe..."):
                try:
                    recipe = parse_recipe_with_claude(content, name_hint)
                    if source_url:
                        recipe["Source URL"] = source_url
                    # Convert tags list to comma string if needed
                    if isinstance(recipe.get("Tags"), list):
                        recipe["Tags"] = recipe["Tags"]
                    at_post("Recipes", recipe)
                    st.success(f"✅ **{recipe.get('Name','Recipe')}** saved to your library!")
                    st.json(recipe)
                except Exception as e:
                    st.error(f"Could not parse recipe: {e}")

    with tab2:
        recipes = get_recipes()
        if not recipes:
            st.info("No recipes yet. Add some in the 'Add Recipe' tab!")
        else:
            st.caption(f"{len(recipes)} recipes saved")
            for r in recipes:
                with st.expander(f"**{r.get('Name','Unnamed')}** — {', '.join(r.get('Meal Type', []))} · {r.get('Calories','?')} cal · {r.get('Protein g','?')}g protein"):
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Calories", r.get("Calories","—"))
                    col2.metric("Protein", f"{r.get('Protein g','—')}g")
                    col3.metric("Carbs", f"{r.get('Carbs g','—')}g")
                    col4.metric("Fat", f"{r.get('Fat g','—')}g")
                    if r.get("Ingredients"):
                        st.markdown("**Ingredients**")
                        st.text(r["Ingredients"])
                    if r.get("Source URL"):
                        st.markdown(f"[View original]({r['Source URL']})")

# ── PAGE: Profile ────────────────────────────────────────────────────────────
elif page == "⚙️ My Profile":
    st.title("My Profile")
    st.caption("Set your daily macro targets, budget, and meal planning preferences.")

    profile = get_profile()

    with st.form("profile_form"):
        st.subheader("Daily macro targets")
        c1, c2, c3 = st.columns(3)
        cal   = c1.number_input("Calories", value=int(profile.get("Calories Target", 2000)), min_value=0)
        prot  = c2.number_input("Protein (g)", value=int(profile.get("Protein Target", 150)), min_value=0)
        carb  = c3.number_input("Carbs (g)", value=int(profile.get("Carbs Target", 200)), min_value=0)
        c4, c5, c6 = st.columns(3)
        fat   = c4.number_input("Fat (g)", value=int(profile.get("Fat Target", 65)), min_value=0)
        fiber = c5.number_input("Fiber (g)", value=int(profile.get("Fiber Target", 30)), min_value=0)
        budget = c6.number_input("Weekly budget ($)", value=float(profile.get("Weekly Budget", 100.0)), min_value=0.0)

        st.subheader("Meal planning preferences")
        c7, c8 = st.columns(2)
        meals_selected = c7.multiselect("Meals to plan", MEAL_TYPES,
            default=profile.get("Meals to Plan", "Breakfast,Lunch,Dinner,Snack").split(",") if profile.get("Meals to Plan") else MEAL_TYPES)
        prep_days = c8.selectbox("Meal prep days per week", [0,1,2,3,7],
            index=[0,1,2,3,7].index(int(profile.get("Meal Prep Days", 2))) if int(profile.get("Meal Prep Days", 2)) in [0,1,2,3,7] else 2)

        c9, c10 = st.columns(2)
        restrict = c9.text_input("Dietary restrictions", value=profile.get("Dietary Restrictions",""), placeholder="e.g. gluten-free, no shellfish")
        servings = c10.number_input("Servings per household", value=int(profile.get("Servings Per Household", 1)), min_value=1)
        notes = st.text_area("Anything else the planner should know?", value=profile.get("Notes",""),
            placeholder="e.g. I love spicy food, prefer quick weeknight dinners...")

        if st.form_submit_button("Save profile", type="primary"):
            save_profile({
                "Calories Target": cal,
                "Protein Target": prot,
                "Carbs Target": carb,
                "Fat Target": fat,
                "Fiber Target": fiber,
                "Weekly Budget": budget,
                "Meals to Plan": ",".join(meals_selected),
                "Meal Prep Days": prep_days,
                "Dietary Restrictions": restrict,
                "Servings Per Household": servings,
                "Notes": notes
            })
            st.success("Profile saved!")

# ── PAGE: Weekly Plan ────────────────────────────────────────────────────────
elif page == "📅 Weekly Plan":
    st.title("Weekly Meal Plan")
    st.caption("AI generates your 7-day plan based on your recipes and macro targets.")

    recipes = get_recipes()
    profile = get_profile()

    if not recipes:
        st.warning("Add some recipes first in the Recipe Library!")
        st.stop()
    if not profile:
        st.warning("Fill out your profile first!")
        st.stop()

    col_a, col_b = st.columns([2,1])
    week_start = col_a.date_input("Week starting", value=date.today() - timedelta(days=date.today().weekday()))

    if st.button("✦ Generate weekly plan", type="primary"):
        with st.spinner("Claude is building your personalized plan — this takes about 20 seconds..."):
            try:
                plan = generate_plan_with_claude(recipes, profile)
                st.session_state["plan"] = plan
                st.session_state["week_start"] = str(week_start)

                # Save to Airtable
                at_delete_all("Weekly Plans")
                at_delete_all("Grocery Lists")

                plan_records = []
                # Build a lookup of recipe name -> airtable record id for linking
                recipe_lookup = {r.get("Name","").lower(): r.get("id") for r in recipes}
                for d in plan.get("days", []):
                    for m in d.get("meals", []):
                        record = {
                            "Week Start Date": str(week_start),
                            "Day": d["day"],
                            "Meal Type": m["type"],
                            "Calories": m.get("calories", 0),
                            "Protein g": m.get("protein", 0),
                            "Carbs g": m.get("carbs", 0),
                            "Fat g": m.get("fat", 0),
                            "Notes": m.get("notes", "")
                        }
                        # Link to recipe record if it exists, otherwise just use name in Notes
                        recipe_name = m["recipe"]
                        linked_id = recipe_lookup.get(recipe_name.lower())
                        if linked_id:
                            record["Recipe"] = [linked_id]
                        else:
                            record["Notes"] = recipe_name + (" — " + m.get("notes","") if m.get("notes") else "")
                        plan_records.append(record)
                at_post_many("Weekly Plans", plan_records)

                grocery_records = []
                for g in plan.get("grocery_list", []):
                    grocery_records.append({
                        "Ingredient": g.get("ingredient",""),
                        "Category": g.get("category","Other"),
                        "Amount": g.get("amount",""),
                        "Est Cost": g.get("cost", 0),
                        "Week Start Date": str(week_start)
                    })
                at_post_many("Grocery Lists", grocery_records)

                st.success("Plan generated and saved to Airtable!")
            except Exception as e:
                st.error(f"Error generating plan: {e}")

    plan = st.session_state.get("plan")
    if plan:
        avg = plan.get("avg_daily_macros", {})
        tgt_cal = profile.get("Calories Target", 2000)
        tgt_prot = profile.get("Protein Target", 150)

        # Stat cards
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Avg calories/day", f"{int(avg.get('calories',0))}", delta=f"{int(avg.get('calories',0))-int(tgt_cal)} vs target")
        m2.metric("Avg protein/day", f"{int(avg.get('protein',0))}g", delta=f"{int(avg.get('protein',0))-int(tgt_prot)}g vs target")
        m3.metric("Avg carbs/day", f"{int(avg.get('carbs',0))}g")
        m4.metric("Est. weekly cost", f"${plan.get('estimated_weekly_cost',0):.0f}", delta=f"${plan.get('estimated_weekly_cost',0)-float(profile.get('Weekly Budget',100)):.0f} vs budget", delta_color="inverse")

        st.markdown("---")

        # Week grid
        cols = st.columns(7)
        for i, day in enumerate(DAYS):
            day_data = next((d for d in plan.get("days",[]) if d["day"]==day), {"meals":[]})
            with cols[i]:
                st.markdown(f"**{day[:3]}**")
                for meal in day_data.get("meals",[]):
                    mtype = meal["type"]
                    color = {"Breakfast":"🌅","Lunch":"☀️","Dinner":"🌙","Snack":"🍎"}.get(mtype,"•")
                    st.markdown(f"{color} **{mtype}**  \n{meal['recipe']}", help=f"{meal.get('calories',0)} cal · {meal.get('protein',0)}g protein")

        # Prep guide
        if plan.get("prep_guide"):
            st.markdown("---")
            st.subheader("Meal prep guide")
            st.info(plan["prep_guide"])

# ── PAGE: Grocery List ───────────────────────────────────────────────────────
elif page == "🛒 Grocery List":
    st.title("Grocery List")
    st.caption("Auto-generated from your weekly plan, organized by category.")

    rows = at_get("Grocery Lists")
    if not rows:
        st.info("Generate your weekly plan first — your grocery list will appear here.")
        st.stop()

    items = [r["fields"] for r in rows]
    total = sum(float(i.get("Est Cost", 0)) for i in items)
    profile = get_profile()
    budget = float(profile.get("Weekly Budget", 100))

    col1, col2 = st.columns(2)
    col1.metric("Total estimated", f"${total:.2f}")
    col2.metric("Weekly budget", f"${budget:.2f}", delta=f"${total-budget:.2f}", delta_color="inverse")

    if total > budget:
        st.warning(f"You're ${total-budget:.2f} over budget. Consider swapping a protein for a more economical option.")
    else:
        st.success(f"You're ${budget-total:.2f} under budget. 🎉")

    st.markdown("---")

    for cat in GROCERY_CATS:
        cat_items = [i for i in items if i.get("Category") == cat]
        if not cat_items:
            continue
        cat_total = sum(float(i.get("Est Cost",0)) for i in cat_items)
        st.subheader(f"{cat}  `${cat_total:.2f}`")
        for item in cat_items:
            checked = item.get("Purchased", False)
            c1, c2, c3 = st.columns([3,1,1])
            c1.write(f"{'~~' if checked else ''}{item.get('Amount','')} {item.get('Ingredient','')}{'~~' if checked else ''}")
            c2.write(f"${float(item.get('Est Cost',0)):.2f}")
        st.markdown("---")

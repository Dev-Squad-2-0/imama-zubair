"""
Day 2 - Task 1: Knowledge Base Data Generation

Generates synthetic, self-consistent datasets for the real estate demo domain.
This is the ONLY file that is domain-specific. To reuse this platform for
another business, shapes described in config/domain_config.yaml.
"""

import os
import random
import pandas as pd
from faker import Faker

random.seed(42)
fake = Faker()
Faker.seed(42)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data")
DOC_DIR = os.path.join(BASE, "documents")

CITIES_AREAS = {
    "Lahore": ["DHA Phase 6", "Bahria Town", "Gulberg", "Johar Town", "Wapda Town"],
    "Karachi": ["DHA Phase 8", "Clifton", "Gulshan-e-Iqbal", "Bahadurabad", "PECHS"],
    "Islamabad": ["Bahria Town", "DHA Phase 2", "F-10", "G-11", "Blue Area"],
}

PROPERTY_TYPES = {
    "buy": ["house", "apartment", "plot"],
    "rent": ["house", "apartment"],
    "commercial": ["shop", "office", "warehouse"],
    "investment": ["plot", "apartment", "shop"],
}

AMENITY_POOL = [
    "24/7 Security", "Community Park", "Gymnasium", "Swimming Pool",
    "Mosque", "Backup Generator", "Underground Electricity", "Wide Roads",
    "Covered Parking", "Kids Play Area", "Shopping Mall Access", "Solar Panels",
]

DEVELOPERS = ["Bahria Developers", "DHA City", "Emaar Pakistan", "Al-Rehman Builders", "Zameen Estates"]


def gen_developers():
    rows = []
    for i, name in enumerate(DEVELOPERS, start=1):
        rows.append({
            "developer_id": i,
            "developer_name": name,
            "founded_year": random.randint(1995, 2015),
            "reputation_score": round(random.uniform(3.5, 5.0), 1),
            "completed_projects": random.randint(5, 60),
        })
    return pd.DataFrame(rows)


def gen_locations():
    rows = []
    loc_id = 1
    for city, areas in CITIES_AREAS.items():
        for area in areas:
            rows.append({
                "location_id": loc_id,
                "city": city,
                "area": area,
                "avg_price_per_marla_pkr": random.randint(1_500_000, 6_000_000),
                "price_trend": random.choice(["rising", "stable", "rising", "declining"]),
            })
            loc_id += 1
    return pd.DataFrame(rows)


def gen_schools(locations_df):
    rows = []
    sid = 1
    for _, loc in locations_df.iterrows():
        for _ in range(random.randint(1, 3)):
            rows.append({
                "school_id": sid,
                "location_id": loc["location_id"],
                "school_name": fake.company() + " School System",
                "distance_km": round(random.uniform(0.3, 4.0), 1),
                "level": random.choice(["Primary", "Secondary", "O/A Levels"]),
            })
            sid += 1
    return pd.DataFrame(rows)


def gen_hospitals(locations_df):
    rows = []
    hid = 1
    for _, loc in locations_df.iterrows():
        for _ in range(random.randint(1, 2)):
            rows.append({
                "hospital_id": hid,
                "location_id": loc["location_id"],
                "hospital_name": fake.company() + " Hospital",
                "distance_km": round(random.uniform(0.5, 6.0), 1),
                "emergency_available": random.choice([True, True, False]),
            })
            hid += 1
    return pd.DataFrame(rows)


def gen_payment_plans():
    plans = []
    for i in range(1, 9):
        down = random.choice([10, 15, 20, 25, 30])
        years = random.choice([2, 3, 5])
        plans.append({
            "plan_id": i,
            "plan_name": f"{down}% Down - {years} Year Installments",
            "down_payment_pct": down,
            "duration_years": years,
            "installment_frequency": random.choice(["Monthly", "Quarterly"]),
        })
    return pd.DataFrame(plans)


def gen_properties(locations_df, developers_df, n=60):
    rows = []
    for i in range(1, n + 1):
        purpose = random.choice(["buy", "rent", "commercial", "investment"])
        ptype = random.choice(PROPERTY_TYPES[purpose])
        loc = locations_df.sample(1, random_state=i).iloc[0]
        dev = developers_df.sample(1, random_state=i).iloc[0]

        if ptype in ("house",):
            size = random.choice([5, 7, 10, 12])
            bedrooms = random.choice([3, 4, 5])
            bathrooms = bedrooms - random.choice([0, 1])
        elif ptype == "apartment":
            size = random.choice([1, 2, 3])
            bedrooms = random.choice([2, 3])
            bathrooms = bedrooms
        elif ptype == "plot":
            size = random.choice([5, 7, 10, 20])
            bedrooms = 0
            bathrooms = 0
        else:  # shop, office, warehouse
            size = random.choice([1, 2, 3, 5])
            bedrooms = 0
            bathrooms = random.choice([0, 1])

        base_price = loc["avg_price_per_marla_pkr"] * max(size, 1)
        if purpose == "rent":
            price = int(base_price * 0.004)  # monthly rent estimate
        else:
            price = int(base_price * random.uniform(0.9, 1.3))

        amenities = random.sample(AMENITY_POOL, k=random.randint(3, 6))

        rows.append({
            "id": i,
            "title": f"{size} Marla {ptype.title()} in {loc['area']}, {loc['city']}",
            "property_type": ptype,
            "purpose": purpose,
            "city": loc["city"],
            "area": loc["area"],
            "location_id": loc["location_id"],
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "size_marla": size,
            "price_pkr": price,
            "status": random.choices(["available", "sold", "rented", "reserved"], weights=[70, 10, 10, 10])[0],
            "developer_id": dev["developer_id"],
            "agent_name": fake.name(),
            "agent_phone": fake.phone_number(),
            "amenities": ", ".join(amenities),
        })
    return pd.DataFrame(rows)


def gen_faqs():
    faqs = [
        ("What documents are needed to buy a property?", "You need your CNIC, proof of income, and a passport size photo. For overseas clients, NICOP is accepted."),
        ("Do you offer installment plans?", "Yes, most of our properties offer flexible payment plans with down payments starting from 10 percent."),
        ("Can overseas Pakistanis buy property remotely?", "Yes, overseas clients can complete the full booking process remotely through video verification and legal power of attorney."),
        ("What is the token amount to book a property?", "Token amount is usually 5 to 10 percent of the total price and is adjusted into the down payment."),
        ("Is the price negotiable?", "Prices have some flexibility depending on the property and how long it has been listed. Our agent can share the best possible rate."),
        ("What happens if I want to cancel after booking?", "Cancellation policy depends on the developer. Typically a portion of the token is non-refundable, our agent will explain the exact terms."),
        ("Do you charge any agent commission?", "Yes, standard agent commission is 1 percent of the sale price for buyers and sellers."),
        ("Are these properties verified and legal?", "All listed properties are verified for clear title and NOC status before being added to our portfolio."),
        ("Can I visit a property before booking?", "Yes, we always recommend a site visit. Our agent can arrange one at your convenience."),
        ("Do you help with property transfer paperwork?", "Yes, our team assists with all transfer paperwork and liaises with the relevant housing authority."),
        ("What is the difference between a token and down payment?", "Token is a small initial commitment amount, down payment is the larger upfront portion of the total price paid at the time of booking."),
        ("Do you have properties near good schools?", "Yes, many of our listings are within a few kilometers of well rated schools. Ask our agent for options near a specific school."),
        ("Is possession immediate after full payment?", "Possession timeline depends on construction status. Ready properties offer immediate possession, under construction ones follow the developer's handover schedule."),
        ("Can I rent out the property after buying it?", "Yes, there are no restrictions on renting out a property you own, subject to society rules in some gated communities."),
        ("Do you provide legal assistance during purchase?", "Yes, we can connect you with panel lawyers who review the sale agreement and title documents."),
        ("What is the typical rental deposit amount?", "Rental deposits are typically equal to one to two months of rent, refundable at the end of tenancy subject to condition of the property."),
        ("Are utility bills included in rent?", "No, utility bills are billed separately to the tenant unless otherwise stated in the rental agreement."),
        ("Can I get a mortgage or bank loan for these properties?", "Yes, several of our listed properties are eligible for bank financing, our agent can guide you on eligible banks."),
        ("How is the price per marla calculated?", "It is based on recent transactions in that area, current demand, and developer pricing for new launches."),
        ("Do you offer virtual property tours?", "Yes, we can arrange a video call walkthrough for clients who cannot visit in person."),
    ]
    return pd.DataFrame(faqs, columns=["question", "answer"])


def write_property_documents(properties_df):
    os.makedirs(os.path.join(DOC_DIR, "brochures"), exist_ok=True)
    os.makedirs(os.path.join(DOC_DIR, "descriptions"), exist_ok=True)

    for _, p in properties_df.iterrows():
        brochure = (
            f"{p['title']}\n\n"
            f"Welcome to your next {p['property_type']} in the heart of {p['area']}, {p['city']}. "
            f"This {p['size_marla']} marla property is designed for modern living, offering a blend of "
            f"comfort and convenience. Surrounded by lush greenery and located in a rapidly developing "
            f"part of {p['city']}, this is an opportunity not to be missed. "
            f"Enjoy premium amenities including {p['amenities']}. "
            f"Developed by {DEVELOPERS[int(p['developer_id']) - 1]}, known for quality construction and "
            f"timely handovers. Contact our agent {p['agent_name']} today to schedule your private viewing "
            f"and secure this property before it's gone.\n"
        )
        with open(os.path.join(DOC_DIR, "brochures", f"property_{p['id']}.txt"), "w") as f:
            f.write(brochure)

        description = (
            f"Property ID: {p['id']}\n"
            f"Type: {p['property_type']}\n"
            f"Purpose: {p['purpose']}\n"
            f"Location: {p['area']}, {p['city']}\n"
            f"Size: {p['size_marla']} marla\n"
            f"Bedrooms: {p['bedrooms']}, Bathrooms: {p['bathrooms']}\n"
            f"Status: {p['status']}\n"
            f"Amenities: {p['amenities']}\n"
            f"This property is located in {p['area']}, an area known for good access to schools and "
            f"hospitals. The surrounding neighborhood has a mix of residential and commercial activity, "
            f"making it convenient for daily errands. Public transport and main roads are within easy reach.\n"
        )
        with open(os.path.join(DOC_DIR, "descriptions", f"property_{p['id']}.txt"), "w") as f:
            f.write(description)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    developers_df = gen_developers()
    locations_df = gen_locations()
    schools_df = gen_schools(locations_df)
    hospitals_df = gen_hospitals(locations_df)
    payment_plans_df = gen_payment_plans()
    properties_df = gen_properties(locations_df, developers_df, n=60)
    faqs_df = gen_faqs()

    developers_df.to_csv(os.path.join(DATA_DIR, "developers.csv"), index=False)
    locations_df.to_csv(os.path.join(DATA_DIR, "locations.csv"), index=False)
    schools_df.to_csv(os.path.join(DATA_DIR, "schools.csv"), index=False)
    hospitals_df.to_csv(os.path.join(DATA_DIR, "hospitals.csv"), index=False)
    payment_plans_df.to_csv(os.path.join(DATA_DIR, "payment_plans.csv"), index=False)
    properties_df.to_csv(os.path.join(DATA_DIR, "properties.csv"), index=False)
    faqs_df.to_csv(os.path.join(DATA_DIR, "faqs.csv"), index=False)

    # amenities as its own lookup table (property_id -> amenity, normalized form)
    amenity_rows = []
    for _, p in properties_df.iterrows():
        for a in p["amenities"].split(", "):
            amenity_rows.append({"property_id": p["id"], "amenity": a})
    pd.DataFrame(amenity_rows).to_csv(os.path.join(DATA_DIR, "amenities.csv"), index=False)

    write_property_documents(properties_df)

    print(f"Generated {len(properties_df)} properties")
    print(f"Generated {len(locations_df)} locations across {len(CITIES_AREAS)} cities")
    print(f"Generated {len(schools_df)} school records")
    print(f"Generated {len(hospitals_df)} hospital records")
    print(f"Generated {len(payment_plans_df)} payment plans")
    print(f"Generated {len(developers_df)} developers")
    print(f"Generated {len(faqs_df)} FAQs")
    print("Generated brochure + description documents for all properties")


if __name__ == "__main__":
    main()

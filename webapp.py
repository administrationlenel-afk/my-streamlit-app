import streamlit as st
import pandas as pd
import requests
import re
import csv
import time
import io
from duckduckgo_search import DDGS


def read_company_csv(uploaded_file):
    """Read a normal CSV or repair the supplied company export format."""
    file_bytes = uploaded_file.getvalue()

    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_bytes.decode("cp1252")

    rows = list(csv.reader(io.StringIO(text)))

    if not rows:
        raise ValueError("The CSV file is empty.")

    headers = [cell.strip() for cell in rows[0]]

    expected_columns = [
        "company_name",
        "company_number",
        "company_status",
        "company_type",
        "company_subtype",
        "dissolution_date",
        "incorporation_date",
        "removed_date",
        "registered_date",
        "nature_of_business",
        "registered_office_address",
    ]

    # Ordinary CSV files use the normal reader.
    supplied_format = (
        headers[:len(expected_columns)] == expected_columns
        and not any(headers[len(expected_columns):])
    )

    if not supplied_format:
        return pd.read_csv(io.StringIO(text), dtype=str)

    records = []

    for line_number, raw_row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in raw_row):
            continue

        row = [cell.strip() for cell in raw_row]

        # Find the company number even if a company name contains commas.
        # The company number must also be followed by company details
        # and then the business activity field.
        candidates = []

        for position in range(1, len(row)):
            is_company_number = re.fullmatch(
                r"(?:\d{8}|[A-Z]{2}\d{6})",
                row[position],
            )

            activity_position = position + 8

            if (
                is_company_number
                and activity_position < len(row)
                and (
                    row[activity_position].startswith("[")
                    or row[activity_position] == ""
                )
            ):
                candidates.append(position)

        if len(candidates) != 1:
            raise ValueError(
                f"CSV row {line_number}: cannot safely identify "
                "the company fields. Please check this row."
            )

        number_position = candidates[0]

        company_name = ", ".join(row[:number_position])
        details = row[number_position:number_position + 8]
        remaining = row[number_position + 8:]

        if remaining[0].startswith("["):
            activity_end = next(
                (
                    position
                    for position, value in enumerate(remaining)
                    if "]" in value
                ),
                None,
            )

            if activity_end is None:
                raise ValueError(
                    f"CSV row {line_number}: the business activity "
                    "codes have a missing closing bracket."
                )

            activity = ",".join(remaining[:activity_end + 1])
            address_parts = remaining[activity_end + 1:]
        else:
            activity = ""
            address_parts = remaining[1:]

        # In this export, the address is the final meaningful field.
        address = ", ".join(
            value for value in address_parts if value
        )

        records.append(
            [company_name] + details + [activity, address]
        )

    return pd.DataFrame(records, columns=expected_columns)


def is_blank(value):
    return pd.isna(value) or str(value).strip() == ""


st.set_page_config(
    page_title="Contact Enrichment Tool",
    layout="wide",
)

st.title("Lead Enrichment Web App")
st.write("Upload an Excel or CSV file to find websites and emails.")

uploaded_file = st.file_uploader(
    "Upload Excel or CSV File",
    type=["xlsx", "csv"],
)

if uploaded_file is not None:
    try:
        if uploaded_file.name.lower().endswith(".csv"):
            df = read_company_csv(uploaded_file)
        else:
            df = pd.read_excel(
                uploaded_file,
                sheet_name=0,
                dtype=str,
            )

        df.columns = [
            str(column).strip() for column in df.columns
        ]

        if df.columns.duplicated().any():
            raise ValueError(
                "Your file contains duplicate column headings. "
                "Please give each column a unique name."
            )

                if "company_name" not in df.columns:
            if "Company" in df.columns or "name" in df.columns:
                source_column = (
                    "Company" if "Company" in df.columns else "name"
                )
                df = df.rename(
                    columns={source_column: "company_name"}
                )
            else:
                raise ValueError(
                    "Your file must contain a company_name, "
                    "Company or name column."
                )

        df = df.reset_index(drop=True)

        if df.empty:
            raise ValueError(
                "Your file contains no company records."
            )

        for column in ["Website", "Scraped_Email"]:
            if column not in df.columns:
                df[column] = None

            df[column] = df[column].astype(object)

    except Exception as error:
        st.error(f"Unable to read the file: {error}")
        st.stop()

    if st.button("Start Enrichment"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        ddgs = DDGS()

        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64)"
            )
        }

        for index, row in df.iterrows():
            company = (
                ""
                if is_blank(row["company_name"])
                else str(row["company_name"]).strip()
            )

            status_text.text(
                f"Processing [{index + 1}/{len(df)}]: "
                f"{company or 'Blank company name'}..."
            )

            # Find Website: original research logic retained.
            if company and is_blank(row["Website"]):
                try:
                    results = ddgs.text(
                        f"{company} UK accounting website",
                        max_results=3,
                    )

                    for result in results or []:
                        website = result.get("href", "")

                        if (
                            "bing.com" not in website
                            and "duckduckgo.com" not in website
                        ):
                            df.at[index, "Website"] = website
                            break

                    time.sleep(1.5)

                except Exception:
                    pass

            # Find Email: original extraction logic retained.
            url = str(df.at[index, "Website"])

            if (
                url.startswith("http")
                and is_blank(row["Scraped_Email"])
            ):
                try:
                    html = requests.get(
                        url,
                        headers=headers,
                        timeout=5,
                    ).text

                    emails = set(
                        re.findall(
                            r"[a-zA-Z0-9._%+-]+"
                            r"@[a-zA-Z0-9.-]+"
                            r"\.[a-zA-Z]{2,}",
                            html,
                        )
                    )

                    valid = [
                        email.lower()
                        for email in emails
                        if not any(
                            email.lower().endswith(extension)
                            for extension in [
                                ".png",
                                ".jpg",
                                ".css",
                                ".js",
                                ".svg",
                            ]
                        )
                    ]

                    df.at[index, "Scraped_Email"] = (
                        ", ".join(valid[:2])
                        if valid
                        else "None found"
                    )

                except Exception:
                    df.at[index, "Scraped_Email"] = (
                        "Connection failed"
                    )

            progress_bar.progress(
                (index + 1) / len(df)
            )

        status_text.text("Complete!")

        output = io.BytesIO()

        with pd.ExcelWriter(
            output,
            engine="openpyxl",
        ) as writer:
            df.to_excel(writer, index=False)

        st.download_button(
            "Download Enriched Data",
            data=output.getvalue(),
            file_name="enriched_contacts_local.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )

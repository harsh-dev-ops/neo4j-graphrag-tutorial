import os
import logging
from contextlib import contextmanager

import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase
from retry import retry


load_dotenv()


class FileConfig:
    CATEGORY_CSV_FILE = os.getenv("CATEGORY_CSV_FILE")
    PRODUCT_CSV_FILE = os.getenv("PRODUCT_CSV_FILE")
    SUPPLIER_CSV_FILE = os.getenv("SUPPLIER_CSV_FILE")
    ORDER_CSV_FILE = os.getenv("ORDER_CSV_FILE")
    ORDER_DETAILS_CSV_FILE = os.getenv("ORDER_DETAILS_CSV_FILE")
    SHIPPER_CSV_FILE = os.getenv("SHIPPER_CSV_FILE")
    EMPLOYEE_CSV_FILE = os.getenv("EMPLOYEE_CSV_FILE")
    CUSTOMER_CSV_FILE = os.getenv("CUSTOMER_CSV_FILE")


class Neo4jConfig:
    NEO4J_URI = os.getenv("NEO4J_URI")
    NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
    NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%d-%m-%Y %H:%M:%S",
)

LOGGER = logging.getLogger(__name__)

NODES = [
    "Product",
    "Category",
    "Supplier",
    "Order",
    "Shipper",
    "Employee",
    "Customer",
]


class Neo4jConnection:
    """Owns the Neo4j driver for a bounded application/ETL scope."""

    def __init__(
        self,
        uri: str,
        username: str,
        password: str,
        database: str = "neo4j",
    ):
        self.uri = uri
        self.username = username
        self.password = password
        self.database = database
        self._driver = None

    def __enter__(self):
        self._driver = GraphDatabase.driver(
            self.uri,
            auth=(self.username, self.password),
        )

        self._driver.verify_connectivity()
        LOGGER.info("Connected to Neo4j database.")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._driver is not None:
            self._driver.close()
            self._driver = None
            LOGGER.info("Neo4j connection closed.")

    @contextmanager
    def session(self):
        if self._driver is None:
            raise RuntimeError(
                "Neo4jConnection must be used inside a 'with' block."
            )

        with self._driver.session(database=self.database) as session:
            yield session


def normalize_neo4j_value(value):
    """
    Convert pandas / NumPy scalar values into values accepted cleanly
    by the Neo4j Python driver.

    Missing pandas values become Python None.
    """
    if pd.isna(value):
        return None

    # Convert NumPy scalar types such as int64 / float64 / bool_
    # into normal Python scalar values.
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass

    # Convert pandas Timestamp to a native Python datetime.
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()

    return value


def pandas_row_to_dict(row: pd.Series) -> dict:
    """Convert a pandas row to a Neo4j-safe parameter dictionary."""
    return {
        key: normalize_neo4j_value(value)
        for key, value in row.items()
    }


def clean_text_columns(
    df: pd.DataFrame,
    columns: list[str],
    missing_value: str = "Unknown",
) -> pd.DataFrame:
    """
    Explicitly treat known textual columns as pandas StringDtype and
    fill their missing values safely.

    This avoids inserting strings into Float64 / Int64 columns.
    """
    for column in columns:
        if column in df.columns:
            df[column] = (
                df[column]
                .astype("string")
                .fillna(missing_value)
            )

    return df


@retry(tries=100, delay=10)
def set_unique_constraints(tx, node):
    constraint_query = (
        f"CREATE CONSTRAINT IF NOT EXISTS "
        f"FOR (n:{node}) REQUIRE n.id IS UNIQUE"
    )
    tx.run(constraint_query)
    LOGGER.info(
        "Unique constraint set for %s nodes on 'id' property.",
        node,
    )


@retry(tries=100, delay=10)
def create_unique_constraints(neo4j: Neo4jConnection):
    LOGGER.info("Setting unique constraints for nodes...")

    with neo4j.session() as session:
        for node in NODES:
            session.execute_write(
                set_unique_constraints,
                node,
            )


@retry(tries=100, delay=10)
def create_manager(tx, row):
    query = """
        MERGE (e:Employee {
            employeeID: $employeeID,
            lastName: $lastName,
            firstName: $firstName,
            title: $title,
            titleOfCourtesy: $titleOfCourtesy,
            birthDate: $birthDate,
            hireDate: $hireDate,
            address: $address_y,
            city: $city_y,
            region: $region_y,
            postalCode: $postalCode_y,
            country: $country_y,
            homePhone: $homePhone,
            extension: $extension,
            photo: $photo,
            notes: $notes,
            photoPath: $photoPath
        })
    """

    params = pandas_row_to_dict(row)
    tx.run(query, parameters=params)


def process_product_category_supplier_csv(
    product_csv_file: str,
    category_csv_file: str,
    supplier_csv_file: str,
):
    try:
        LOGGER.info(
            "Reading data from %s, %s, and %s...",
            product_csv_file,
            category_csv_file,
            supplier_csv_file,
        )

        products_df = pd.read_csv(product_csv_file)
        category_df = pd.read_csv(category_csv_file)
        supplier_df = pd.read_csv(supplier_csv_file)

        LOGGER.info("Merging product and category data...")

        product_category_df = pd.merge(
            products_df,
            category_df,
            on="categoryID",
        )

        LOGGER.info(
            "Merging product-category data with supplier data..."
        )

        product_category_supplier_df = pd.merge(
            product_category_df,
            supplier_df,
            on="supplierID",
            how="left",
        )

        LOGGER.info("Cleaning product/category/supplier data...")

        # Convert to pandas nullable dtypes first.
        product_category_supplier_df = (
            product_category_supplier_df.convert_dtypes()
        )

        product_supplier_text_columns = [
            "productName",
            "quantityPerUnit",
            "categoryName",
            "description",
            "picture",
            "companyName",
            "contactName",
            "contactTitle",
            "address",
            "city",
            "region",
            "postalCode",
            "country",
            "phone",
            "fax",
            "homePage",
        ]

        product_category_supplier_df = clean_text_columns(
            product_category_supplier_df,
            product_supplier_text_columns,
        )

        return product_category_supplier_df

    except Exception as exc:
        LOGGER.exception(
            "Error processing product/category/supplier CSV files: %s",
            exc,
        )
        raise


def insert_data(tx, row):
    query = """
        CREATE (product:Product {
            productID: $productID,
            productName: $productName,
            supplierID: $supplierID,
            categoryID: $categoryID,
            quantityPerUnit: $quantityPerUnit,
            unitPrice: $unitPrice,
            unitsInStock: $unitsInStock,
            unitsOnOrder: $unitsOnOrder,
            reorderLevel: $reorderLevel,
            discontinued: $discontinued
        })

        MERGE (category:Category {
            categoryID: $categoryID,
            categoryName: $categoryName,
            description: $description,
            picture: $picture
        })

        MERGE (supplier:Supplier {
            supplierID: $supplierID,
            companyName: $companyName,
            contactName: $contactName,
            contactTitle: $contactTitle,
            address: $address,
            city: $city,
            region: $region,
            postalCode: $postalCode,
            country: $country,
            phone: $phone,
            fax: $fax,
            homePage: $homePage
        })

        CREATE (product)-[:PART_OF]->(category)
        CREATE (product)-[:SUPPLIED_BY]->(supplier)
    """

    params = pandas_row_to_dict(row)
    tx.run(query, parameters=params)


@retry(tries=100, delay=10)
def load_product_category_supply_into_graph(
    neo4j: Neo4jConnection,
    product_category_supplier_df: pd.DataFrame,
):
    LOGGER.info(
        "Inserting product, category, and supplier data "
        "into Neo4j graph..."
    )

    with neo4j.session() as session:
        for _, row in product_category_supplier_df.iterrows():
            session.execute_write(
                insert_data,
                row,
            )

    LOGGER.info("Product/category/supplier insertion complete.")


def process_order_order_details_shipper_employee_customer_csv(
    order_csv_file: str,
    order_details_csv_file: str,
    shipper_csv_file: str,
    employee_csv_file: str,
    customer_csv_file: str,
):
    try:
        LOGGER.info(
            "Reading order, order details, shipper, employee, "
            "and customer CSV files..."
        )

        orders_df = pd.read_csv(order_csv_file)
        order_details_df = pd.read_csv(order_details_csv_file)
        shipper_df = pd.read_csv(shipper_csv_file)
        employee_df = pd.read_csv(employee_csv_file)
        customer_df = pd.read_csv(customer_csv_file)

        LOGGER.info("Merging order and order details data...")

        orders_order_details_df = pd.merge(
            orders_df,
            order_details_df,
            on="orderID",
            how="left",
        )

        LOGGER.info(
            "Merging order/order-details data with customer data..."
        )

        orders_order_details_customer_df = pd.merge(
            orders_order_details_df,
            customer_df,
            on="customerID",
            how="left",
        )

        LOGGER.info(
            "Merging order/customer data with shipper data..."
        )

        orders_order_details_customer_shipper_df = pd.merge(
            orders_order_details_customer_df,
            shipper_df,
            left_on="shipVia",
            right_on="shipperID",
            how="left",
        )

        LOGGER.info(
            "Merging order/customer/shipper data with employee data..."
        )

        orders_order_details_customer_shipper_employee_df = pd.merge(
            orders_order_details_customer_shipper_df,
            employee_df,
            on="employeeID",
            how="left",
        )

        LOGGER.info("Cleaning merged order data...")

        df = (
            orders_order_details_customer_shipper_employee_df
            .convert_dtypes()
        )

        # These columns are semantically textual.
        #
        # Explicitly defining them is safer than relying only on
        # select_dtypes(), because an entirely empty CSV text column can
        # initially be inferred as numeric.
        text_columns = [
            # Order
            "orderDate",
            "requiredDate",
            "shippedDate",
            "shipName",
            "shipAddress",
            "shipCity",
            "shipRegion",
            "shipPostalCode",
            "shipCountry",

            # Customer
            "customerID",
            "companyName_x",
            "contactName",
            "contactTitle",
            "address_x",
            "city_x",
            "region_x",
            "postalCode_x",
            "country_x",
            "phone_x",
            "fax",

            # Shipper
            "companyName_y",
            "phone_y",

            # Employee
            "lastName",
            "firstName",
            "title",
            "titleOfCourtesy",
            "birthDate",
            "hireDate",
            "address_y",
            "city_y",
            "region_y",
            "postalCode_y",
            "country_y",
            "homePhone",
            "extension",
            "photo",
            "notes",
            "photoPath",
        ]

        df = clean_text_columns(
            df,
            text_columns,
        )

        # reportsTo is a numeric employee ID.
        # Northwind's top-level employee has no manager; preserve the
        # existing ETL behavior by using employee ID 2 as the fallback.
        if "reportsTo" in df.columns:
            df["reportsTo"] = (
                pd.to_numeric(
                    df["reportsTo"],
                    errors="coerce",
                )
                .astype("Int64")
                .fillna(2)
            )

        return df

    except Exception as exc:
        LOGGER.exception(
            "Error processing order-related CSV files: %s",
            exc,
        )
        raise


def insert_manager_record(
    neo4j: Neo4jConnection,
    orders_order_details_customer_shipper_employee_df: pd.DataFrame,
):
    LOGGER.info(
        "Creating Vice President record in Neo4j graph..."
    )

    vice_president = (
        orders_order_details_customer_shipper_employee_df[
            orders_order_details_customer_shipper_employee_df[
                "title"
            ] == "Vice President"
        ]
    )

    LOGGER.info(
        "Inserting manager records into Neo4j graph..."
    )

    with neo4j.session() as session:
        for _, row in vice_president.iterrows():
            if row["reportsTo"] != 2:
                session.execute_write(
                    create_manager,
                    row,
                )

    LOGGER.info("Manager record insertion complete.")


def order_order_details_shippers_employees_and_customer_data_ingester(
    tx,
    row,
):
    query = """
        CREATE (o:Order {
            orderID: $orderID,
            orderDate: $orderDate,
            requiredDate: $requiredDate,
            shippedDate: $shippedDate,
            shipVia: $shipVia,
            freight: $freight,
            shipName: $shipName,
            shipAddress: $shipAddress,
            shipCity: $shipCity,
            shipRegion: $shipRegion,
            shipPostalCode: $shipPostalCode,
            shipCountry: $shipCountry
        })

        WITH o

        MATCH (p:Product {
            productID: $productID
        })

        WITH p, o

        MERGE (c:Customer {
            customerID: $customerID,
            companyName: $companyName_x,
            contactName: $contactName,
            contactTitle: $contactTitle,
            address: $address_x,
            city: $city_x,
            region: $region_x,
            postalCode: $postalCode_x,
            country: $country_x,
            phone: $phone_x,
            fax: $fax
        })

        WITH c, p, o

        MERGE (s:Shipper {
            shipperID: $shipperID,
            companyName: $companyName_y,
            phone: $phone_y
        })

        WITH s, c, p, o

        MERGE (e:Employee {
            employeeID: $employeeID,
            lastName: $lastName,
            firstName: $firstName,
            title: $title,
            titleOfCourtesy: $titleOfCourtesy,
            birthDate: $birthDate,
            hireDate: $hireDate,
            address: $address_y,
            city: $city_y,
            region: $region_y,
            postalCode: $postalCode_y,
            country: $country_y,
            homePhone: $homePhone,
            extension: $extension,
            photo: $photo,
            notes: $notes,
            photoPath: $photoPath
        })

        WITH e, s, c, p, o

        MATCH (m:Employee {
            employeeID: $reportsTo
        })

        WITH m, e, s, c, p, o

        MERGE (e)-[:REPORTS_TO]->(m)
        MERGE (o)-[:INCLUDES]->(p)
        MERGE (o)-[:ORDERED_BY]->(c)
        MERGE (o)-[:SHIPPED_BY]->(s)
        MERGE (o)-[:PROCESSED_BY]->(e)
    """

    params = pandas_row_to_dict(row)
    tx.run(query, parameters=params)


@retry(tries=100, delay=10)
def load_order_order_details_shippers_employees_and_customer_data_into_graph(
    neo4j: Neo4jConnection,
    orders_order_details_customer_shipper_employee_df: pd.DataFrame,
):
    LOGGER.info(
        "Inserting order, order details, shippers, employees, "
        "and customer data into Neo4j graph..."
    )

    with neo4j.session() as session:
        for _, row in (
            orders_order_details_customer_shipper_employee_df.iterrows()
        ):
            session.execute_write(
                order_order_details_shippers_employees_and_customer_data_ingester,
                row,
            )

    LOGGER.info("Order-related data insertion complete.")


def validate_required_config():
    required_file_config = {
        "CATEGORY_CSV_FILE": FileConfig.CATEGORY_CSV_FILE,
        "PRODUCT_CSV_FILE": FileConfig.PRODUCT_CSV_FILE,
        "SUPPLIER_CSV_FILE": FileConfig.SUPPLIER_CSV_FILE,
        "ORDER_CSV_FILE": FileConfig.ORDER_CSV_FILE,
        "ORDER_DETAILS_CSV_FILE": FileConfig.ORDER_DETAILS_CSV_FILE,
        "SHIPPER_CSV_FILE": FileConfig.SHIPPER_CSV_FILE,
        "EMPLOYEE_CSV_FILE": FileConfig.EMPLOYEE_CSV_FILE,
        "CUSTOMER_CSV_FILE": FileConfig.CUSTOMER_CSV_FILE,
    }

    required_neo4j_config = {
        "NEO4J_URI": Neo4jConfig.NEO4J_URI,
        "NEO4J_USERNAME": Neo4jConfig.NEO4J_USERNAME,
        "NEO4J_PASSWORD": Neo4jConfig.NEO4J_PASSWORD,
    }

    missing = [
        name
        for name, value in {
            **required_file_config,
            **required_neo4j_config,
        }.items()
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
        )


def main():
    LOGGER.info(
        "\n\n"
        "+++++++++++++++++ Starting ETL process +++++++++++++++++"
        "\n\n"
    )

    validate_required_config()

    product_category_supplier_df = (
        process_product_category_supplier_csv(
            FileConfig.PRODUCT_CSV_FILE,
            FileConfig.CATEGORY_CSV_FILE,
            FileConfig.SUPPLIER_CSV_FILE,
        )
    )

    orders_order_details_customer_shipper_employee_df = (
        process_order_order_details_shipper_employee_customer_csv(
            FileConfig.ORDER_CSV_FILE,
            FileConfig.ORDER_DETAILS_CSV_FILE,
            FileConfig.SHIPPER_CSV_FILE,
            FileConfig.EMPLOYEE_CSV_FILE,
            FileConfig.CUSTOMER_CSV_FILE,
        )
    )

    with Neo4jConnection(
        uri=Neo4jConfig.NEO4J_URI,
        username=Neo4jConfig.NEO4J_USERNAME,
        password=Neo4jConfig.NEO4J_PASSWORD,
        database=Neo4jConfig.NEO4J_DATABASE,
    ) as neo4j:
        create_unique_constraints(neo4j)

        load_product_category_supply_into_graph(
            neo4j,
            product_category_supplier_df,
        )

        insert_manager_record(
            neo4j,
            orders_order_details_customer_shipper_employee_df,
        )

        load_order_order_details_shippers_employees_and_customer_data_into_graph(
            neo4j,
            orders_order_details_customer_shipper_employee_df[:250],
        )

    LOGGER.info(
        "\n\n"
        "+++++++++++++++++ ETL process completed +++++++++++++++++"
        "\n\n"
    )


if __name__ == "__main__":
    main()

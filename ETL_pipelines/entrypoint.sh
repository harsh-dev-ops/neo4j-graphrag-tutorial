#!/bin/bash

# Run any setup steps or pre-processing tasks here
echo "Running ETL to move Northwind data from csvs to Neo4j..."

# Run the ETL script
python3  ETL_pipelines/main.py
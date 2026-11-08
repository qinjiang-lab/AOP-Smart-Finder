# AOP-Smart-Finder

**A High-Throughput Human–AI Hybrid Framework for AOP Discovery and Evidence Mapping from Large-Scale Literature**

## Overview

AOP-Smart-Finder is a Windows-based tool for discovering adverse outcome pathways (AOPs) and mapping evidence from large-scale literature using commercial large language models (LLMs). It supports two analysis modes: compound-based literature analysis and event-based literature analysis.

> **Current limitation:** AOP-Smart-Finder currently runs on Windows only.

## Requirements

- **Windows**
- **Python** installed on your system. Python 3.12.8 is provided as a reference version:  
  https://www.python.org/downloads/release/python-3128/
  - During installation, make sure to select **“Add python.exe to PATH”**.
- **Web of Science exported Excel files** as literature input.
- A **commercial LLM API key** and **Base URL** for literature analysis.

## Installation and Quick Start

1. Download and extract the package to a local folder.
2. Ensure Python is installed and available in PATH.
3. Prepare your Web of Science Excel file(s) as described below.
4. Double-click **`AOP-Smart-Finder.bat`** to run the program.

## Preparing Literature Data

You need to search literature in **Web of Science** and export the results as an Excel file.

When exporting, select **at least** the following fields:

- Title
- Source
- Abstract

Place the exported Excel file in the program folder.

### File Naming for Compound-Based Mode

If you use the **compound-based literature analysis mode**, the file name **must exactly match the compound name**, for example:

- `DEHP.xlsx`
- `DBP.xlsx`

## Merging Large Web of Science Exports

Web of Science allows exporting at most **1,000 records at a time**. A merge utility is provided for larger result sets.

1. Export records in batches, e.g. 1–1000, 1001–2000, etc.
2. Place the exported files in the **`merge`** folder.
3. Double-click **`run_merge.bat`**.
4. Enter the desired name for the merged file.
5. The merged file will be placed in the **`merge`** folder.
6. Move the merged file out of the `merge` folder into the main program folder.
7. Run **`AOP-Smart-Finder.bat`**.

If you do not need to merge files, simply run **`AOP-Smart-Finder.bat`** directly.

## LLM API Configuration

AOP-Smart-Finder uses commercial LLMs for literature analysis. **This requires a paid API key.** Please refer to each provider’s pricing and rate limits.

Supported LLM providers include:

| Provider | Link |
|---|---|
| DeepSeek | https://platform.deepseek.com/ |
| GPT (OpenAI) | https://platform.openai.com/ |
| Gemini | https://aistudio.google.com/ |
| OpenRouter (aggregated LLM platform with 100+ models) | https://openrouter.ai/ |

An API key is required before analysis can proceed.

Common Base URL examples:

- **DeepSeek:** `https://api.deepseek.com`
- **OpenRouter:** `https://openrouter.ai/api/v1`

The file **`workflow.pdf`** documents a previous AOP-Smart workflow and can serve as an initial reference for understanding how to configure the API key and Base URL.

## Running the Analysis

During execution, the program will prompt you to enter the number of concurrent threads. The default is **20**. Please refer to the concurrency and rate limits of your chosen LLM provider.

## Analysis Modes

AOP-Smart-Finder provides two analysis modes.

### Mode 1: Compound-Based Literature Analysis

1. Select mode **1**.
2. Enter the compound name.
3. Optionally provide a one-sentence prompt describing the toxicity or mechanism you want the LLM to focus on. This can be left blank.
4. Run the program and wait for the analysis to finish.

The program will create a folder named after the compound in the current directory, e.g. `./<compound_name>/`. The final output is:

- **`AOP_network.xlsx`**

This file can be imported directly into **Cytoscape** for analysis. The Excel file also includes hyperlinks to the literature for convenient checking.

### Mode 2: Event-Based Literature Analysis

1. Select mode **2**.
2. The compound name is not required.
3. Focus on configuring your event list of interest.

Example prompt:

> "Prioritize extracting causal relationships involving increases in reactive oxygen species (ROS), oxidative stress, TDP-43 aggregation, mitochondrial dysfunction, neuroinflammation, decreases in neuronal network function, and human amyotrophic lateral sclerosis (ALS)."

Write the prompt as **a single line without line breaks**, then wait for the results.

## Notes

- The design of the Web of Science search query is very important at the initial literature retrieval stage.
- AOP-Smart-Finder currently supports **Windows only**.
- Commercial LLM usage may incur costs. Please check the provider’s pricing and rate limits before running large-scale analyses.
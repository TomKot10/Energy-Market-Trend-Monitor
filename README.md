# 🔍 Energy Trend Monitor (LLM + Python)

## 🚀 Overview
Energy Trend Monitor is an automated system for collecting and analyzing current trends in the energy sector using Python and a local Large Language Model (LLM). 
The project implements a complete end-to-end pipeline that transforms unstructured news data into structured analytical insights. 
It retrieves the latest articles from the energy section of WNP.pl through web scraping, processes and cleans the extracted content, and then uses a locally deployed language model via Ollama (qwen2.5:3b) to perform semantic analysis. 
As a result, each article is enriched with key information such as keywords, sentiment classification, main topic, and a concise summary.

## ⚙️ Technology
The solution is built using Python and leverages requests for data retrieval, BeautifulSoup for HTML parsing, and pandas for data processing and export. 
The analytical layer is powered by a local LLM running through Ollama, which enables text understanding without relying on paid external APIs. 
The output is stored in both JSON and CSV formats, making it easy to integrate with further analytical tools or dashboards.

## 🧠 LLM & Prompt Design
A key aspect of the implementation is prompt engineering, which ensures that the language model produces structured and reliable output. 
The model is constrained to operate strictly on the provided input data, without introducing external knowledge or generating unsupported claims. This approach minimizes hallucinations and enforces a consistent JSON structure. Additional validation logic is applied after inference to further improve robustness and data quality.

## 📊 Output & Results
The system generates a structured report that includes per-article analysis and aggregated insights. Each article is described using keywords, sentiment, main topic, and a short summary. 
In addition, the model identifies a dominant cross-article trend, providing a concise explanation and a business implication. This allows for quick interpretation of market dynamics and emerging patterns in the energy sector.

## 📈 Business Insight
The analysis indicates a clear acceleration of the energy transition as the dominant trend across the latest articles. The content highlights increased focus on nuclear energy development, including small modular reactors (SMR), 
alongside regulatory changes and ongoing concerns related to energy security. From a business perspective, this suggests that energy companies should accelerate investments in new technologies while simultaneously managing the risks associated with structural changes in the sector.

## 🔄 Future Development
The project can be easily extended to include additional data sources, time-based trend analysis, or integration with interactive dashboards such as Power BI or Streamlit. This makes it a scalable foundation for building real-world market monitoring systems.

## 🎯 Conclusion
This project demonstrates how LLM-based solutions can be effectively integrated into data pipelines to transform unstructured text into actionable business insights. 
It combines web scraping, natural language processing, and structured reporting into a single, practical workflow that can support data-driven decision-making in a dynamic market environment.

##    Author
Tomasz Kotliński

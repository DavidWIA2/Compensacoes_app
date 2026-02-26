# Compensacoes_app

Sistema desenvolvido em Python para controle e gerenciamento dos plantios de compensações ambientais referentes às árvores suprimidas no município de São Carlos - SP.

---

## 📌 Contexto do Problema

A supressão de árvores exige compensação ambiental conforme legislação vigente. O controle manual dessas informações pode gerar inconsistências, dificuldade de rastreamento e perda de dados ao longo do tempo.

O Compensacoes_app foi desenvolvido para organizar, estruturar e facilitar a gestão dessas compensações por meio de uma aplicação com interface gráfica e leitura de planilha padronizada.

---

## 🚀 Funcionalidades

- Leitura automatizada de planilha de compensações
- Organização estruturada dos registros
- Controle de plantios realizados e pendentes
- Interface gráfica desenvolvida com PySide6
- Estrutura modular preparada para expansão
- Separação entre dados, lógica e interface

---

## 🛠 Tecnologias Utilizadas

- Python
- PySide6 (Interface gráfica)
- Manipulação de planilhas Excel
- Estrutura modular de aplicação
- Controle de dependências via requirements.txt

---

## 📊 Planilha Modelo

O sistema utiliza uma planilha padrão para leitura e organização dos dados.

Um arquivo modelo com dados fictícios está disponível na pasta:

data/modelo_planilha_compensacoes.xlsx

A estrutura da planilha deve manter os mesmos cabeçalhos presentes no modelo para que o sistema funcione corretamente.

---

## 📂 Estrutura do Projeto

Compensacoes_app/
│
├── app/                     → Código principal da aplicação
├── assets/                  → Recursos visuais
├── data/                    → Planilha modelo e arquivos de dados
├── run.py                   → Arquivo principal de execução
└── requirements.txt         → Dependências do projeto

---

## ▶️ Como Executar

Clone o repositório:

git clone https://github.com/DavidWIA2/Compensacoes_app.git
cd Compensacoes_app

Crie e ative um ambiente virtual:

python -m venv .venv
.venv\Scripts\activate

Instale as dependências:

pip install -r requirements.txt

Execute a aplicação:

python run.py

---

## 👨‍💻 Autor

David Wiliam Pinheiro de Oliveira  
Estudante de Tecnologia da Informação (3º semestre)  
Foco em Desenvolvimento de Software e Dados
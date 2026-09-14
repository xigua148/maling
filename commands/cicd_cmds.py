"""CI/CD 配置生成命令：/cicd init|add — 生成 CI/CD 流水线配置模板。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from commands.router import CommandRouter, CommandContext
from core import G, R, Y, C, GR


# 预设 CI/CD 模板
_GITHUB_ACTIONS_TEMPLATES: Dict[str, str] = {
    "python": '''name: Python CI

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.9', '3.10', '3.11', '3.12']

    steps:
    - uses: actions/checkout@v4

    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v5
      with:
        python-version: ${{ matrix.python-version }}

    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt

    - name: Run tests
      run: |
        pytest --cov=src --cov-report=xml

    - name: Lint
      run: |
        flake8 src tests
        black --check src tests
''',
    "node": '''name: Node.js CI

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node-version: [18.x, 20.x, 22.x]

    steps:
    - uses: actions/checkout@v4

    - name: Use Node.js ${{ matrix.node-version }}
      uses: actions/setup-node@v4
      with:
        node-version: ${{ matrix.node-version }}
        cache: 'npm'

    - name: Install dependencies
      run: npm ci

    - name: Run tests
      run: npm test

    - name: Build
      run: npm run build
''',
    "go": '''name: Go CI

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        go-version: ['1.21', '1.22', '1.23']

    steps:
    - uses: actions/checkout@v4

    - name: Set up Go
      uses: actions/setup-go@v5
      with:
        go-version: ${{ matrix.go-version }}

    - name: Download dependencies
      run: go mod download

    - name: Run tests
      run: go test -v -race ./...

    - name: Build
      run: go build -v ./...
''',
}

_GITLAB_CI_TEMPLATES: Dict[str, str] = {
    "python": '''stages:
  - test
  - build

variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"

cache:
  paths:
    - .cache/pip
    - venv/

test:python3.11:
  stage: test
  image: python:3.11-slim
  before_script:
    - python -m venv venv
    - source venv/bin/activate
    - pip install -r requirements.txt
  script:
    - pytest --cov=src --cov-report=xml
  coverage: '/TOTAL.*\\s+(\\d+%)$/'

lint:
  stage: test
  image: python:3.11-slim
  before_script:
    - pip install flake8 black
  script:
    - flake8 src tests
    - black --check src tests
''',
    "node": '''stages:
  - test
  - build

cache:
  paths:
    - node_modules/

test:
  stage: test
  image: node:20-slim
  before_script:
    - npm ci
  script:
    - npm test

build:
  stage: build
  image: node:20-slim
  before_script:
    - npm ci
  script:
    - npm run build
  artifacts:
    paths:
      - dist/
''',
}

_JENKINS_TEMPLATES: Dict[str, str] = {
    "python": '''pipeline {
    agent any

    stages {
        stage('Install') {
            steps {
                sh 'python -m pip install --upgrade pip'
                sh 'pip install -r requirements.txt'
            }
        }
        stage('Test') {
            steps {
                sh 'pytest --cov=src --cov-report=xml'
            }
        }
        stage('Lint') {
            steps {
                sh 'flake8 src tests || true'
                sh 'black --check src tests || true'
            }
        }
    }

    post {
        always {
            junit '**/test-*.xml'
        }
    }
}
''',
    "node": '''pipeline {
    agent any

    stages {
        stage('Install') {
            steps {
                sh 'npm ci'
            }
        }
        stage('Test') {
            steps {
                sh 'npm test'
            }
        }
        stage('Build') {
            steps {
                sh 'npm run build'
            }
        }
    }

    post {
        always {
            junit '**/test-*.xml'
        }
    }
}
''',
}

_ADDON_STEPS: Dict[str, str] = {
    "docker": '''    - name: Build Docker image
      run: docker build -t myapp:${{ github.sha }} .
''',
    "deploy": '''    - name: Deploy to staging
      run: |
        echo "${{ secrets.SSH_KEY }}" > key.pem
        chmod 600 key.pem
        scp -i key.pem -r dist/ user@server:/var/www/app
''',
    "security": '''    - name: Security scan
      run: |
        pip install bandit safety
        bandit -r src/
        safety check
''',
    "notify": '''    - name: Notify Slack
      uses: slackapi/slack-github-action@v1
      with:
        payload: |
          {"text": "Build ${{ job.status }} for ${{ github.repository }}"}
      env:
        SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
''',
}


def register_cicd_commands(router: CommandRouter) -> None:
    """注册 CI/CD 配置生成命令。"""

    @router.command(
        "cicd",
        description="生成 CI/CD 配置模板（GitHub/GitLab/Jenkins）",
        usage="/cicd init [github|gitlab|jenkins] | /cicd add <step>",
        category="开发者工具",
    )
    def cmd_cicd(ctx: CommandContext) -> None:
        sub = ctx.args[0] if ctx.args else ""

        if sub == "init":
            _cmd_cicd_init(ctx)
        elif sub == "add":
            _cmd_cicd_add(ctx)
        else:
            print("用法: /cicd init [github|gitlab|jenkins]  — 生成 CI/CD 配置")
            print("       /cicd add <step>                  — 添加步骤到现有配置")
            print("\n支持平台: github, gitlab, jenkins")
            print("可选步骤: docker, deploy, security, notify")


def _detect_project_type() -> str:
    """根据项目文件检测类型。"""
    if Path("requirements.txt").exists() or Path("pyproject.toml").exists():
        return "python"
    if Path("package.json").exists():
        return "node"
    if Path("go.mod").exists():
        return "go"
    if Path("pom.xml").exists():
        return "java"
    if Path("Cargo.toml").exists():
        return "rust"
    return "python"  # 默认


def _cmd_cicd_init(ctx: CommandContext) -> None:
    """生成 CI/CD 配置文件。"""
    platform = ctx.args[1] if len(ctx.args) > 1 else "github"
    project_type = _detect_project_type()

    if platform not in ("github", "gitlab", "jenkins"):
        print(R(f"❌ 不支持的平台: {platform}。支持: github, gitlab, jenkins"))
        return

    print(C(f"🔧 检测到项目类型: {project_type}"))
    print(C(f"🔧 生成 {platform} CI/CD 配置...\n"))

    if platform == "github":
        template = _GITHUB_ACTIONS_TEMPLATES.get(project_type)
        if not template:
            template = _GITHUB_ACTIONS_TEMPLATES.get("python")
            print(Y(f"⚠️ {project_type} 暂无专用模板，使用 Python 模板作为基础"))
        output_path = Path(".github/workflows/ci.yml")
        output_path.parent.mkdir(parents=True, exist_ok=True)

    elif platform == "gitlab":
        template = _GITLAB_CI_TEMPLATES.get(project_type)
        if not template:
            template = _GITLAB_CI_TEMPLATES.get("python")
            print(Y(f"⚠️ {project_type} 暂无专用模板，使用 Python 模板作为基础"))
        output_path = Path(".gitlab-ci.yml")

    else:  # jenkins
        template = _JENKINS_TEMPLATES.get(project_type)
        if not template:
            template = _JENKINS_TEMPLATES.get("python")
            print(Y(f"⚠️ {project_type} 暂无专用模板，使用 Python 模板作为基础"))
        output_path = Path("Jenkinsfile")

    if output_path.exists():
        confirm = input(Y(f"⚠️ {output_path} 已存在，覆盖？(y/N): ")).strip().lower()
        if confirm != "y":
            print("已取消。")
            return

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(template)
        print(G(f"✅ 已生成 {output_path}"))
        print(GR(f"\n预览（前 20 行）:"))
        lines = template.splitlines()
        for line in lines[:20]:
            print(GR(f"  {line}"))
        if len(lines) > 20:
            print(GR(f"  ... 共 {len(lines)} 行"))
    except Exception as e:
        print(R(f"❌ 写入失败: {e}"))


def _cmd_cicd_add(ctx: CommandContext) -> None:
    """添加步骤到现有 CI/CD 配置。"""
    step = ctx.args[1] if len(ctx.args) > 1 else None
    if not step:
        print("用法: /cicd add <step>")
        print("可选步骤: docker, deploy, security, notify")
        return

    if step not in _ADDON_STEPS:
        print(R(f"❌ 未知步骤: {step}"))
        print(f"可选步骤: {', '.join(_ADDON_STEPS.keys())}")
        return

    # 检测现有配置
    config_file = None
    platform = None
    if Path(".github/workflows/ci.yml").exists():
        config_file = Path(".github/workflows/ci.yml")
        platform = "github"
    elif Path(".github/workflows/main.yml").exists():
        config_file = Path(".github/workflows/main.yml")
        platform = "github"
    elif Path(".gitlab-ci.yml").exists():
        config_file = Path(".gitlab-ci.yml")
        platform = "gitlab"
    elif Path("Jenkinsfile").exists():
        config_file = Path("Jenkinsfile")
        platform = "jenkins"

    if not config_file:
        print(Y("⚠️ 未找到现有 CI/CD 配置，请先执行 /cicd init"))
        return

    if platform != "github":
        print(Y(f"⚠️ 当前仅支持向 GitHub Actions 配置添加步骤（检测到 {platform}）"))
        print(f"步骤内容:\n{_ADDON_STEPS[step]}")
        return

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(R(f"❌ 读取失败: {e}"))
        return

    # 简单插入策略：在最后一个 step 之前插入新步骤
    addon = _ADDON_STEPS[step]
    # 查找 "    - name:" 最后一次出现的位置，在其后插入
    last_step_idx = content.rfind("    - name:")
    if last_step_idx == -1:
        # 尝试更宽松的缩进
        last_step_idx = content.rfind("    - ")

    if last_step_idx != -1:
        # 找到该行的行尾
        line_end = content.find("\n", last_step_idx)
        if line_end == -1:
            line_end = len(content)
        # 在该行后插入
        new_content = content[:line_end] + "\n" + addon + content[line_end:]
    else:
        # 找不到合适位置，追加到文件末尾
        new_content = content + "\n" + addon

    try:
        with open(config_file, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(G(f"✅ 已添加 '{step}' 步骤到 {config_file}"))
    except Exception as e:
        print(R(f"❌ 写入失败: {e}"))

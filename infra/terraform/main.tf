data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

locals {
  name               = var.project_name
  container_image    = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"
  use_https          = var.certificate_arn != ""
  oidc_issuer        = "https://demo.tool-permission-enforcer.invalid"
  oidc_audience      = "tool-permission-enforcer"

  # PostgreSQL configuration
  database_name      = "permission_enforcer"

  # DO NOT use "permission" because it is a PostgreSQL reserved word.
  database_user      = "appuser"

  availability_zones = slice(data.aws_availability_zones.available.names, 0, 2)
}

resource "aws_vpc" "main" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${local.name}-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-igw" }
}

resource "aws_subnet" "public" {
  count = 2

  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index + 1)
  availability_zone       = local.availability_zones[count.index]
  map_public_ip_on_launch = true

  tags = { Name = "${local.name}-public-${count.index + 1}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${local.name}-public" }
}

resource "aws_route_table_association" "public" {
  count = 2

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Public traffic to the permission proxy load balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ingress_cidr]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.allowed_ingress_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name}-alb" }
}

resource "aws_security_group" "ecs" {
  name        = "${local.name}-ecs"
  description = "Only the ALB can reach the permission proxy"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Proxy from ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name}-ecs" }
}

resource "aws_security_group" "database" {
  name        = "${local.name}-database"
  description = "PostgreSQL access from ECS only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL from ECS"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name}-database" }
}

resource "aws_db_subnet_group" "main" {
  name       = "${local.name}-database"
  subnet_ids = aws_subnet.public[*].id
}

resource "random_password" "database" {
  length  = 32
  special = false
}

resource "random_password" "crm_api_key" {
  length  = 48
  special = false
}

resource "random_password" "session_signing_secret" {
  length  = 64
  special = false
}

resource "aws_db_instance" "main" {
  identifier = "${local.name}-postgres"

  engine                 = "postgres"
  engine_version         = "16"
  instance_class         = "db.t4g.micro"
  allocated_storage      = 20
  max_allocated_storage  = 50
  storage_type           = "gp3"
  storage_encrypted      = true
  db_name                = local.database_name
  username               = local.database_user
  password               = random_password.database.result
  port                   = 5432
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false

  backup_retention_period = 1
  multi_az                = false
  deletion_protection     = false
  skip_final_snapshot     = true
  apply_immediately       = true
}

resource "aws_secretsmanager_secret" "runtime" {
  name                    = "${local.name}/runtime"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "runtime" {
  secret_id = aws_secretsmanager_secret.runtime.id
  secret_string = jsonencode({
    PROXY_DATABASE_URL           = "postgresql+psycopg://${local.database_user}:${random_password.database.result}@${aws_db_instance.main.address}:5432/${local.database_name}"
    CRM_DATABASE_URL             = "postgresql+psycopg://${local.database_user}:${random_password.database.result}@${aws_db_instance.main.address}:5432/${local.database_name}"
    PROXY_CRM_INTERNAL_API_KEY   = random_password.crm_api_key.result
    CRM_INTERNAL_API_KEY         = random_password.crm_api_key.result
    PROXY_DEV_JWT_SECRET         = var.demo_jwt_secret
    PROXY_SESSION_SIGNING_SECRET = random_password.session_signing_secret.result
  })
}

resource "aws_ecr_repository" "app" {
  name                 = local.name
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the ten newest demo images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.name}"
  retention_in_days = 14
}

resource "aws_iam_role" "execution" {
  name = "${local.name}-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "runtime_secret" {
  name = "read-runtime-secret"
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = aws_secretsmanager_secret.runtime.arn
    }]
  })
}

resource "aws_iam_role" "task" {
  name = "${local.name}-task"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_lb" "main" {
  name               = substr(local.name, 0, 32)
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
}

resource "aws_lb_target_group" "proxy" {
  name        = substr("${local.name}-proxy", 0, 32)
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    enabled             = true
    path                = "/health/ready"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 15
    matcher             = "200"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = local.use_https ? "redirect" : "forward"

    dynamic "redirect" {
      for_each = local.use_https ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }

    target_group_arn = local.use_https ? null : aws_lb_target_group.proxy.arn
  }
}

resource "aws_lb_listener" "https" {
  count = local.use_https ? 1 : 0

  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.proxy.arn
  }
}

locals {
  common_log_configuration = {
    logDriver = "awslogs"
    options = {
      awslogs-group         = aws_cloudwatch_log_group.app.name
      awslogs-region        = var.aws_region
      awslogs-stream-prefix = "service"
    }
  }
  runtime_secret_arn = aws_secretsmanager_secret.runtime.arn
}

resource "aws_ecs_task_definition" "app" {
  count = var.create_service ? 1 : 0

  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "database-migrate"
      image     = local.container_image
      essential = false
      command   = ["sh", "-c", "alembic upgrade head && python -m scripts.seed_phase_1"]
      environment = [
        { name = "PROXY_APP_ENV", value = "staging" }
      ]
      secrets = [
        { name = "PROXY_DATABASE_URL", valueFrom = "${local.runtime_secret_arn}:PROXY_DATABASE_URL::" }
      ]
      logConfiguration = local.common_log_configuration
    },
    {
      name      = "sample-crm"
      image     = local.container_image
      essential = true
      command   = ["uvicorn", "services.sample_crm.main:app", "--host", "0.0.0.0", "--port", "8001"]
      dependsOn = [{ containerName = "database-migrate", condition = "SUCCESS" }]
      environment = [
        { name = "CRM_APP_ENV", value = "production" },
        { name = "CRM_LOG_LEVEL", value = "INFO" },
        { name = "CRM_PORT", value = "8001" }
      ]
      secrets = [
        { name = "CRM_DATABASE_URL", valueFrom = "${local.runtime_secret_arn}:CRM_DATABASE_URL::" },
        { name = "CRM_INTERNAL_API_KEY", valueFrom = "${local.runtime_secret_arn}:CRM_INTERNAL_API_KEY::" }
      ]
      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health/ready', timeout=3)\" || exit 1"]
        interval    = 15
        timeout     = 5
        retries     = 3
        startPeriod = 20
      }
      linuxParameters  = { initProcessEnabled = true }
      logConfiguration = local.common_log_configuration
    },
    {
      name      = "permission-proxy"
      image     = local.container_image
      essential = true
      command   = ["uvicorn", "services.permission_proxy.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*"]
      dependsOn = [{ containerName = "sample-crm", condition = "HEALTHY" }]
      portMappings = [{
        name          = "proxy"
        containerPort = 8000
        hostPort      = 8000
        protocol      = "tcp"
      }]
      environment = [
        { name = "PROXY_APP_ENV", value = "staging" },
        { name = "PROXY_LOG_LEVEL", value = "INFO" },
        { name = "PROXY_PORT", value = "8000" },
        { name = "PROXY_CRM_BASE_URL", value = "http://127.0.0.1:8001" },
        { name = "PROXY_UPSTREAM_TIMEOUT_SECONDS", value = "5" },
        { name = "PROXY_OIDC_ISSUER", value = local.oidc_issuer },
        { name = "PROXY_OIDC_AUDIENCE", value = local.oidc_audience },
        { name = "PROXY_DEV_AUTH_ENABLED", value = "true" },
        { name = "PROXY_SESSION_TOKEN_ISSUER", value = "tool-permission-enforcer" },
        { name = "PROXY_SESSION_TOKEN_AUDIENCE", value = "agent-session" },
        { name = "PROXY_SESSION_TOKEN_TTL_SECONDS", value = "1800" }
      ]
      secrets = [
        { name = "PROXY_DATABASE_URL", valueFrom = "${local.runtime_secret_arn}:PROXY_DATABASE_URL::" },
        { name = "PROXY_CRM_INTERNAL_API_KEY", valueFrom = "${local.runtime_secret_arn}:PROXY_CRM_INTERNAL_API_KEY::" },
        { name = "PROXY_DEV_JWT_SECRET", valueFrom = "${local.runtime_secret_arn}:PROXY_DEV_JWT_SECRET::" },
        { name = "PROXY_SESSION_SIGNING_SECRET", valueFrom = "${local.runtime_secret_arn}:PROXY_SESSION_SIGNING_SECRET::" }
      ]
      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)\" || exit 1"]
        interval    = 15
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
      linuxParameters  = { initProcessEnabled = true }
      logConfiguration = local.common_log_configuration
    }
  ])

  depends_on = [
    aws_iam_role_policy_attachment.execution,
    aws_iam_role_policy.runtime_secret,
    aws_secretsmanager_secret_version.runtime
  ]
}

resource "aws_ecs_service" "app" {
  count = var.create_service ? 1 : 0

  name                               = local.name
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.app[0].arn
  desired_count                      = 1
  launch_type                        = "FARGATE"
  platform_version                   = "1.4.0"
  health_check_grace_period_seconds  = 90
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
  wait_for_steady_state              = true

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.proxy.arn
    container_name   = "permission-proxy"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http]
}

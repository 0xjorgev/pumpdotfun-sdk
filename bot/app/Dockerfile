FROM public.ecr.aws/lambda/python:3.12-arm64

WORKDIR /var/task
# Install dependencies
RUN dnf update -y && dnf install -y zip gcc gcc-c++ make glibc-devel && dnf clean all

COPY requirements.txt .
COPY ./api ${LAMBDA_TASK_ROOT}/api
COPY main.py ${LAMBDA_TASK_ROOT}

# Install Solders
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt 


# Command for Lambda
CMD ["main.handler"]

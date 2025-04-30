FROM public.ecr.aws/lambda/python:3.12-arm64

# ENV LANG=en_US.UTF-8
# ENV TZ=:/etc/localtime
# ENV PATH=/var/lang/bin:/usr/local/bin:/usr/bin/:/bin:/opt/bin
# ENV LD_LIBRARY_PATH=/var/lang/lib:/lib64:/usr/lib64:/var/runtime:/var/runtime/lib:/var/task:/var/task/lib:/opt/lib
# ENV LAMBDA_TASK_ROOT=/var/task
# ENV LAMBDA_RUNTIME_DIR=/var/runtime

WORKDIR /var/task
# Install dependencies
RUN dnf update -y && dnf install -y zip gcc gcc-c++ make glibc-devel && dnf clean all

COPY requirements.txt .
COPY lambda_function.py ${LAMBDA_TASK_ROOT}

# Install Solders
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt 
# RUN python -m venv .venv
# RUN source .venv/bin/activate
# RUN pip install --no-cache-dir -r requirements.txt --target python/lib/python3.12/site-packages/
# RUN zip -r layer.zip python

# Copy function code
# COPY lambda_function.py ${LAMBDA_TASK_ROOT}


# Command for Lambda
CMD ["lambda_function.lambda_handler"]
#ENTRYPOINT ["/lambda-entrypoint.sh"]
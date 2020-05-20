FROM drupal:8
ARG DB_URL
ARG DB_NAME
ARG DB_UNAME
ARG DB_PASSWORD
ARG ACCOUNT_UNAME
ARG ACCOUNT_PASSWORD
ARG SITE_NAME
ARG ACCOUNT_EMAIL
# Install packages
RUN rm /bin/sh && ln -s /bin/bash /bin/sh && \
    apt-get update && apt-get install --no-install-recommends -y \
    curl \
    wget \
    vim \
    git \
    zip \
    unzip \
    mysql-client \
    nano

# Install Composer
RUN curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer && \
    ln -s /root/.composer/vendor/bin/drush /usr/local/bin/drush

# Install Drush
RUN composer global require drush/drush:8 --update-with-all-dependencies && \
    composer global update

# Clean repository
RUN apt-get clean && rm -rf /var/lib/apt/lists/*
RUN export PATH="$HOME/.composer/vendor/bin:$PATH"
RUN drush status

RUN echo --db-url=mysql://${DB_UNAME}:${DB_PASSWORD}@${DB_URL}:3306/${DB_NAME} --account-name=$ACCOUNT_UNAME --account-pass=$ACCOUNT_PASSWORD --site-name=$SITE_NAME --account-mail=$ACCOUNT_EMAIL --site-mail=$ACCOUNT_EMAIL
# Install and configure website with database information
RUN drush site-install --db-url=mysql://${DB_UNAME}:${DB_PASSWORD}@${DB_URL}:3306/${DB_NAME} --account-name=$ACCOUNT_UNAME --account-pass=$ACCOUNT_PASSWORD --site-name=$SITE_NAME -y
RUN drush -y config-set system.performance css.preprocess 0
RUN drush status
#RUN /etc/init.d/apache2 start
EXPOSE 80

#coding=utf-8
import time
import random
import smtplib
from email.utils import formataddr
from email.mime.text import MIMEText

MAIL_LIST = [("lazygetmoneybackup@163.com", "WBMUMNKLBSPPDWYW", "smtp.163.com"),
             ("245568216@qq.com", "wdnbnaparvvfbiai", "smtp.qq.com"),
             ("aixuezhongdenanhai@163.com", "DRMRDAKOCCZIZXAD", "smtp.163.com"),
             ("lazygetmoney@163.com", "DHNYZYLRRFCKWENX", "smtp.163.com")]


class MailNew(object):

    def __init__(self, sender_name, subject, content, my_receiver, content_type='plain'):
        self.my_sender, self.my_pass, self.url = random.choice(MAIL_LIST)
        print("my_sender:", self.my_sender)
        self.sender_name = sender_name
        self.receiver_addr = my_receiver
        self.subject = subject
        self.content = content
        self.content_type = content_type

    def send(self):
        try:
            msg = MIMEText(
                str(self.content),
                self.content_type,
                'utf-8',
            )
            msg['From'] = formataddr([self.sender_name, self.my_sender])
            msg['to'] = '订阅用户'
            msg['Subject'] = self.subject
            server = smtplib.SMTP_SSL(self.url, 465)
            server.login(self.my_sender, self.my_pass)
            server.sendmail(self.my_sender, self.receiver_addr, msg.as_string())
            server.quit()
            print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())) + ' 邮件发送成功')
            return self.my_sender
        except Exception as e:
            print(str(e))
            return False


if __name__ == '__main__':
    title = "邮箱验证码"
    content = '<html>{}</html>'
    body = '<table border="1" class="dataframe">\n  <thead>\n    <tr style="text-align: right;">\n      <th></th>\n      <th>time</th>\n      <th>open</th>\n      <th>now</th>\n      <th>high</th>\n      <th>low</th>\n      <th>turnover</th>\n      <th>volume</th>\n      <th>no1</th>\n      <th>range</th>\n      <th>diff_value</th>\n    </tr>\n  </thead>\n  <tbody>\n    <tr>\n      <th>1822</th>\n      <td>2022-04-19</td>\n      <td>57.65</td>\n      <td>57.30</td>\n      <td>58.15</td>\n      <td>57.06</td>\n      <td>168495</td>\n      <td>971057232.00</td>\n      <td>1.89</td>\n      <td>-0.47</td>\n      <td>-0.27</td>\n    </tr>\n    <tr>\n      <th>1823</th>\n      <td>2022-04-20</td>\n      <td>57.75</td>\n      <td>57.56</td>\n      <td>58.89</td>\n      <td>57.00</td>\n      <td>216628</td>\n      <td>1255101328.00</td>\n      <td>3.30</td>\n      <td>0.45</td>\n      <td>0.26</td>\n    </tr>\n    <tr>\n      <th>1824</th>\n      <td>2022-04-21</td>\n      <td>57.10</td>\n      <td>56.03</td>\n      <td>57.99</td>\n      <td>55.60</td>\n      <td>280000</td>\n      <td>1586256608.00</td>\n      <td>4.15</td>\n      <td>-2.66</td>\n      <td>-1.53</td>\n    </tr>\n  </tbody>\n</table>'
    content = content.format(body)
    address = "378997468@qq.com"
    MailNew('推送通知', title, content, address, "163").send()
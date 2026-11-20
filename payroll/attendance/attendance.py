"""Attendance check.

The day-by-day rules are the October 2026 script, parameterised by month
and file path so the same file can run every month. It also records one
fact per person per day for payroll.
"""

from datetime import datetime
from pathlib import Path
import pandas as pd
import re, os

from payroll.core.config import HOUR_STANDARD, SHOP_LIST, SKIPROWS

file_path1 = ""
month_sheet = ""
shop_list = SHOP_LIST
skiprow_num = SKIPROWS
hour_st = HOUR_STANDARD
location = ""
FACTS = []


def time_change(hour1):
    re_hour1 = hour1
    try:
        hour1 = float(hour1)
        if hour1 < 0:
            re_hour1 = 0
    except:
        pass
    return re_hour1


def time_str(list_time):
    list11 = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
              'Jul', 'Aug', 'Sept', 'Oct', 'Nov', 'Dec']
    re_list = []

    for str1 in list_time:
        try:
            date1 = datetime.strptime(str(str1)[0:10], '%Y-%m-%d')
            year1 = str(date1.year)[2:]
            month1 = list11[date1.month]
            day1 = date1.day
            str2 = '{}-{}-{}'.format(day1, month1, year1)
        except:
            str2 = str1
        re_list.append(str2)
    return re_list


def list_extend(books):
    # 将每个员工的时长列表汇总在一起
    re_list = ['時長列表']
    for name1, col1 in books.items():
        list1 = []
        if name1 in 'items':
            continue
        for list11 in col1.values:
            try:
                list1.extend(list11)
            except:
                pass
        list1 = [i for i in list1 if i != 0.0]
        re_list.append(list1)
    return re_list


def xiaban(book):
    # 获取最晚下班时间
    list1 = []
    # 按行遍历
    for index, row in book.iterrows():
        col_list = list(book.columns.values)
        num1 = len(col_list)
        str11, str1 = 'nan','nan'
        time11 = datetime(2001, 1, 1, 0, 0)
        for i in range(num1-1,1,-1):
            if '下班' in col_list[i]:
                if '地點' not in col_list[i] and '位置' not in col_list[i]:
                    if ':' in str(row[col_list[i]]):
                        time1 = '2020/01/01 {}'.format(str(row[col_list[i]]))
                        time1 = datetime.strptime(time1, '%Y/%m/%d %H:%M')
                        if time1 > time11:
                            time11 = time1
                            str11 = row[col_list[i]]
        if time11 > datetime(2001, 1, 1, 0, 0):
            str1 = str11
        list1.append(str1)
    return list1


def huizong(data5,books):
    # 汇总员工打卡數据
    # 分组遍历
    datas = pd.DataFrame()
    for name1, group in books.groupby('items'):
        if name1 == '時長列表':
            group.loc['合计'] = list_extend(group)
        else:
            # with pd.option_context("future.no_silent_downcasting", True):
            group = group.fillna(0)
            group.loc['合计'] = group.sum(numeric_only=None)
        group = group.reset_index(drop=True)
        num2 = group.shape[0]

        if name1 == '時長列表':
            list_row = group.iloc[num2 - 1]
            list11 = ['時長列表']
            for list1 in list(list_row)[1:]:
                list11.append(hour_st*60)
            group1 = pd.DataFrame(data=[list11], columns=books.columns)
            datas = pd.concat([datas, group1])
        else:
            group.at[num2 - 1, 'items'] = name1
            group.drop(group.index[0:num2 - 1], inplace=True)  # 删除行
            datas = pd.concat([datas, group])

    datas = datas.set_index('items')
    datas = datas.T
    datas = datas.reset_index()
    datas = pd.merge(datas, data5, how='left', on='Name') 
    datas['本月剩餘休假'] = datas['上月剩餘休假'] - datas['本月休假天數']
    datas['本月剩餘年假'] = datas['上月剩餘年假'] - datas['本月年假天數']
    datas['本月應工作時長'] = 0
    # datas['本月應工作時長'] = datas['工作天數'] * datas['時長列表']
    # datas['本月應工作時長'] = datas.apply(lambda x: x['本月應工作時長'] if 'PT' not in x['Name'] else 0, axis=1)
    datas['本月加班時長'] = datas['工作時長'] - datas['本月應工作時長']
    datas.drop(columns=['工作時長', '工作天數', '時長列表', '本月應工作時長'], inplace=True)
    col_list = ['Name', '遲到次數', '遲到分鐘', '早退次數', '早退分鐘', '上月剩餘休假', '本月休假天數',
                '本月剩餘休假', '上月剩餘年假', '本月年假天數', '本月剩餘年假', '本月加班時長']
    datas = datas[col_list]
    return datas


def _as_date(day1):
    try:
        return pd.to_datetime(day1).strftime("%Y-%m-%d")
    except Exception:
        return str(day1)[:10]


def _record_fact(facts, name, day1, roster_raw, result, working_hours,
                 d_late, d_lm, d_early, d_em, d_hol, d_al, matched):
    if facts is None:
        return
    result_s = "" if result is None else str(result)
    roster_s = "" if roster_raw is None else str(roster_raw)
    if result_s == "nan":
        result_s = ""
    if roster_s == "nan":
        roster_s = ""
    facts.append({
        "shop": location,
        "name": name,
        "date": _as_date(day1),
        "roster": roster_s,
        "result": result_s,
        "ot_hours": float(working_hours or 0),
        "late": int(d_late),
        "late_mins": int(d_lm),
        "early": int(d_early),
        "early_mins": int(d_em),
        "rest_day": int(d_hol),
        "annual_leave": int(d_al),
        "missing_punch": int(("缺卡" in result_s) or ("缺失" in result_s)),
        "wrong_site": int("異地打卡" in result_s),
        "in_daka": int(matched),
    })


def time_verify(book, data2, shop_name, col_lists, facts=None):
    '''
    核对打卡时间和排班表的时间
    '''
    # 修改店名
    for shop_list1 in shop_list:
        if shop_name in shop_list1:
            shop_name = shop_list1[1]
    day_list = list(data2.columns.values[1:15])      # 工作时间
    list_col = time_str(list(data2.columns.values))  # 转化列的时间格式
    data3_list = [list_col]                          # 第一行數据，是时间
    book['日期'] = pd.to_datetime(book['日期'])        # 转化时间格式
    # 遍历每一个人，一周的工作时间
    for index1, row1 in data2.iterrows():
        list1 = list(row1.values)  # 每一行的數据
        if 'Name' in list1[0]:
            continue
        num_late, num_leave, time_late, time_leave = 0, 0, 0, 0
        num_annual_leave, num_holiday, work_nums, work_hour, hour_list = 0, 0, 0, 0, []
        # 筛选打卡表里的人员
        book1 = book.loc[book['姓名'] == list1[0]]
        if book1.shape[0] > 0:
            daystr_list3 = []
            # 遍历当周每一天时间
            # day_list：列名，每一天的时间
            for index11, day1 in enumerate(day_list):
                time_work = list1[index11 + 1]  # 排班表里，当天的工作时间安排
                roster_raw = time_work
                # '00'说明是打卡时间列
                if '00' in str(day1):
                    snap_late, snap_lm = num_late, time_late
                    snap_early, snap_em = num_leave, time_leave
                    snap_hol, snap_al = num_holiday, num_annual_leave
                    time_work1 = ''  # 工作状态，是否有迟到早退缺卡等
                    working_hours = 0  # 用于计算打卡表里的下班时间和编更表里的上班时间之间的工作时长
                    if '休假' in str(time_work):
                        num_holiday += 1       # 休假了一天
                    elif '年假' in str(time_work):
                        num_annual_leave += 1  # 年假休了一天
                    else:
                        # 筛选指定日期
                        book11 = book1.loc[book1['日期'] == day1]
                        # 正常工作，且有打卡记录
                        if book11.shape[0] > 0:
                            # 排班表若调整店铺，就更新店铺名
                            shop1 = re.findall(r'(.{0,})\d{2}:\d{2}-\d{2}:\d{2}', str(time_work))  # 工作店铺
                            if len(shop1) > 0 and len(shop1[0]) > 0:
                                shop_name = shop1[0].strip()
                            # 排班表里上班打卡和下班打卡
                            time1 = re.findall(r'(\d{1,2}:\d{1,2})-', str(time_work))
                            time2 = re.findall(r'-(\d{1,2}:\d{1,2})', str(time_work))
                            if len(time1) > 0 and len(time2) > 0:
                                str_verify = ''
                                # 排班表里上班打卡和下班打卡
                                time11 = datetime.strptime('2020-01-01 {}'.format(time1[0]), '%Y-%m-%d %H:%M')
                                time22 = datetime.strptime('2020-01-01 {}'.format(time2[0]), '%Y-%m-%d %H:%M')
                                book11 = book11.reset_index(drop=True)
                                # 对每一天的打卡记录进行处理
                                list11 = list(book11.iloc[0, :].values)  # 打卡时间、位置
                                if 'nan' in str(list11[2]) and 'nan' not in str(list11[-2]):
                                    time_work = '上班缺卡'
                                elif 'nan' not in str(list11[2]) and 'nan' in str(list11[-2]):
                                    time_work = '下班缺卡'
                                elif 'nan' in str(list11[2]) and 'nan' in str(list11[-2]):
                                    time_work = '全天缺卡'
                                else:
                                    # 打卡记录里上班打卡和下班打卡
                                    time31 = datetime.strptime('2020-01-01 {}'.format(list11[2]), '%Y-%m-%d %H:%M')
                                    time32 = datetime.strptime('2020-01-01 {}'.format(list11[-2]), '%Y-%m-%d %H:%M')
                                    hour11 = (time32 - time22).seconds // 60  # 打卡下班时间-排班下班时间
                                    # 大于等于30分钟算加班，否则不算加班
                                    if time32 > time22 and hour11 >= 30:
                                        working_hours = ((time32 - time22).seconds // 1800)/2  # 计算加班时长
                                        str_verify += '加班{}小時-'.format(working_hours)
                                        # if 'PT' in list1[0]:
                                        #     # 兼职员工，计算加班时长
                                        #     working_hours = (time32 - time22).seconds // 60
                                        # else:
                                        #     # 正式员工，计算工作时长
                                        #     working_hours = (time32 - time11).seconds // 60  # 当天工作时长
                                    else:
                                        # 工作时长为0
                                        working_hours = 0
                                        # if 'PT' in list1[0]:
                                        #     # 兼职员工，计算工作时长为0
                                        #     working_hours = 0
                                        # else:
                                        #     # 正式员工，工作时长就是当天的排班表
                                        #     working_hours = (time22 - time11).seconds // 60

                                    if time11 < time31:
                                        str_verify += '遲到-'
                                        num_late += 1
                                        min1 = (time31-time11).seconds//60  # 遲到分鐘數
                                        time_late += min1
                                    if time22 > time32:
                                        min1 = (time22 - time32).seconds // 60  # 早退分鐘數
                                        if min1 <= 60:
                                            num_leave += 1
                                            str_verify += '早退-'
                                            time_leave += min1
                                        else:
                                            str_verify += '下班缺卡'
                                    if shop_name not in str(list11[-1]) and shop_name not in str(list11[-3]):
                                        str_verify += '異地打卡'
                                    # 如果有异常情况，把异常情况记录在内
                                    if len(str_verify.strip()) > 0:
                                        str_verify = str_verify.strip()
                                        time_work = '{} 排班表：{}；內勤表：{}{} {}{}'.format(str_verify, time_work,
                                                                                           list11[-3], list11[2],
                                                                                           list11[-1], list11[-2])
                                        time_work = time_work.replace('nan', '')
                        else:
                            # 没有当天的打卡數据
                            time_work = '全天缺卡'
                        time_work1 = time_work
                        # 没有缺卡的，才能判断为真实工作天数
                        if ':' in str(time_work) and '缺卡' not in str(time_work):
                            work_nums += 1  # 工作天數+1
                    _record_fact(
                        facts, list1[0], day1, roster_raw, time_work, working_hours,
                        num_late - snap_late, time_late - snap_lm,
                        num_leave - snap_early, time_leave - snap_em,
                        num_holiday - snap_hol, num_annual_leave - snap_al, 1,
                    )
                else:
                    # 说明是工作时长列，time_work是分配的工作时长
                    if 'nan' in str(time_work) or '0.0' == str(time_work):
                        pass
                    elif '缺卡' in str(time_work1):
                        time_work1 = ''
                        pass
                    else:
                        hour_list.append(time_work)
                        work_hour += working_hours   # 工作時長，需要加上当天实际的工作時長
                daystr_list3.append(time_work)
            # 數据整合在一起
            list111 = [list1[0]]
            list111.extend(daystr_list3)
            list111.extend([num_late, time_late, num_leave, time_leave, num_holiday,
                            num_annual_leave, work_nums, work_hour, hour_list])
            data3_list.append(list111)
        else:
            # 没有这个人的打卡數据
            list111 = [list1[0]]
            list111.extend(['缺失打卡' for i in range(1, 15)])
            list111.extend([num_late, time_late, num_leave, time_leave, num_holiday,
                            num_annual_leave, work_nums, work_hour, hour_list])
            data3_list.append(list111)
            if facts is not None:
                for day1 in day_list:
                    if '00' in str(day1):
                        _record_fact(facts, list1[0], day1, '', '缺失打卡', 0, 0, 0, 0, 0, 0, 0, 0)

    # 转为數据格式
    data3 = pd.DataFrame(data=data3_list, columns=col_lists)
    data3.loc[' '] = ''
    data3.loc['  '] = ''

    return data3


def datapro(file_path2, facts=None):
    books = pd.DataFrame()
    # 1.读取打卡表，采用不同编码方式，读取文件
    for encoding_word in ['UTF-8', 'utf-8-sig', 'ANSI', 'Unicode', 'GB18030']:
        try:
            book = pd.read_csv(file_path1, encoding=encoding_word)
            break
        except:
            continue
    # 获取最晚下班时间
    book['下班'] = xiaban(book)
    # 删除不需要的列
    book.drop(book.columns[14:], axis=1, inplace=True)
    book.drop(book.columns[9:12], axis=1, inplace=True)
    book.drop(book.columns[4:7], axis=1, inplace=True)
    book.drop(book.columns[1:3], axis=1, inplace=True)

    # 2.读取編更表
    data1 = pd.read_excel(file_path2, month_sheet, skiprows=skiprow_num)
    shop_name = data1.iloc[[0], [0]].values[0][0]  # 店铺名称
    data1 = data1.dropna(thresh=2)
    col_lists = ['Name', '星期一', '', '星期二', '', '星期三', '', '星期四', '',
                 '星期五', '', '星期六', '', '星期日', '', '遲到次數', '遲到分鐘',
                 '早退次數', '早退分鐘', '本月休假天數', '本月年假天數', '工作天數', '工作時長', '時長列表']
    # 3.按行遍历，获取每周的安排
    datas = pd.DataFrame()
    week_list, week_list1 = [], []
    start_row = 999999
    week_num = 0  # 用于判断是第几个周
    for index1, row1 in data1.iterrows():
        # 判断是否是第一行
        if list(row1.values)[0] == shop_name:
            if len(week_list) > 0:
                week_num += 1  # 用于判断是第几个周
                # 生成一周的數据
                col_name = week_list[0]
                col_name[0] = 'Name'
                data2 = pd.DataFrame(week_list[1:], columns=col_name)
                data2 = data2.dropna(subset=['Name'])
                data2['遲到次數'] = 0
                data2['遲到分鐘'] = 0
                data2['早退次數'] = 0
                data2['早退分鐘'] = 0
                data2['本月休假天數'] = 0
                data2['本月年假天數'] = 0
                data2['工作天數'] = 0
                data2['工作時長'] = 0
                data2['時長列表'] = 0
                data3 = time_verify(book, data2, shop_name, col_lists, facts)  # 检验是否有遲到早退
                datas = pd.concat([datas, data3])

                # 单独提取第一个周的休假數据
                if week_num == 1:
                    data5 = pd.DataFrame(week_list1)
                    data5.drop(data5.columns[1:16], axis=1, inplace=True)
                    data5.drop(data5.columns[6:], axis=1, inplace=True)
                    data5.drop(data5.columns[3:5], axis=1, inplace=True)
                    data5.columns = ['Name', '上月剩餘休假', '當月休假', '上月剩餘年假']
                    data5['上月剩餘休假'] = data5['上月剩餘休假'] + data5['當月休假']
                    data5.drop(data5.columns[[2]], axis=1, inplace=True)
                    data5.drop(book.index[[0, 1]], inplace=True)  # 删除行
                    data5 = data5.dropna(thresh=1)  # 员工上月剩余休假 剩余年假
                # 汇总计算员工遲到早退的數据
                data4 = data3.copy()
                data4 = data4.reset_index(drop=True)
                num22 = data4.shape[0]
                data4.drop(data4.columns[1:15], axis=1, inplace=True)
                data4.drop(book.index[[0, num22 - 2, num22 - 1]], inplace=True)  # 删除行
                data4 = data4.set_index('Name')
                data4 = data4.T
                data4 = data4.reset_index()
                books = pd.concat([books, data4])

            # 重新生成新的一周數据
            start_row = index1
            week_list = []
        # 如果当周數据开始，就收录
        if index1 > start_row:
            week_list.append(list(row1.values)[:15])
            week_list1.append(list(row1.values))  # 用于提取休假年假數据
    # 生成一周的數据
    col_name = week_list[0]
    col_name[0] = 'Name'

    data2 = pd.DataFrame(week_list[1:], columns=col_name)
    data2 = data2.dropna(subset=['Name'])
    data2['遲到次數'] = 0
    data2['遲到分鐘'] = 0
    data2['早退次數'] = 0
    data2['早退分鐘'] = 0
    data2['本月休假天數'] = 0
    data2['本月年假天數'] = 0
    data2['工作天數'] = 0
    data2['工作時長'] = 0
    data2['時長列表'] = 0
    # 4.调用函數，进行检验
    data3 = time_verify(book,data2,shop_name,col_lists, facts)  # 检验是否有遲到早退
    datas = pd.concat([datas, data3])
    datas.drop(datas.columns[15:], axis=1, inplace=True)

    # 5.汇总计算员工遲到早退的數据
    data4 = data3.copy()
    data4 = data4.reset_index(drop=True)
    num22 = data4.shape[0]
    data4.drop(data4.columns[1:15], axis=1, inplace=True)
    data4.drop(book.index[[0, num22-2, num22-1]], inplace=True)  # 删除行
    data4 = data4.set_index('Name')
    data4 = data4.T
    data4 = data4.reset_index()
    books = pd.concat([books, data4])
    books.rename(columns={'index': 'items'}, index={1: 'a'}, inplace=True)

    # 计算员工的汇总數据
    books = huizong(data5, books)
    books['本月加班時長'] = books['本月加班時長'].apply(time_change)
    return books,datas


def data_save(books, datas):
    # 把数据写入表格
    format1 = workbook.add_format({
        "font_name": u"宋体",
        "font_size": 11,
        'text_wrap': True,  # 是否自动换行
        'valign': 'vcenter',  # 垂直对齐方式
        'align': 'center',  # 水平对齐方式
        'border': 1  # 四个边框
    })
    format2 = workbook.add_format({
        "font_name": u"宋体",
        "font_size": 11,
        'bold': True,
        'text_wrap': True,
        'fg_color': 'FFFF00',  # 背景颜色
        'valign': 'vcenter',
        'align': 'center',
        'border': 1
    })
    format3 = workbook.add_format({
        "font_name": u"宋体",
        "font_size": 11,
        'bold': True,
        'font_color': 'FF0000',  # 字体颜色
        'text_wrap': True,
        'fg_color': 'FFFF00',  # 背景颜色
        'valign': 'vcenter',
        'align': 'center',
        'border': 1
    })
    # 保存每周考勤數据
    datas.to_excel(writer, sheet_name=location, index=False)
    worksheet1 = writer.sheets[location]
    datas = datas.reset_index()
    datas = datas.replace('nan', '')
    list_str = ['遲到', '早退', '缺失', '缺卡', '異地打卡', '加班']
    for index11, row2 in datas.iterrows():
        for index21, rowstr in enumerate(row2):
            if str(rowstr) == 'nan':
                worksheet1.write(index11 + 1, index21 - 1, '', format1)
            elif str(rowstr) == 'NaN':
                worksheet1.write(index11 + 1, index21 - 1, '', format1)
            else:
                worksheet1.write(index11 + 1, index21-1, str(rowstr), format1)
                # 如果有特定打卡记录，就备注颜色
                for str1 in list_str:
                    if str1 in str(rowstr):
                        if '加班' in str(rowstr):
                            worksheet1.write(index11 + 1, index21-1, str(rowstr), format3)
                        else:
                            worksheet1.write(index11 + 1, index21 - 1, str(rowstr), format2)
                        break

    # 写入汇总數据
    row_nums = datas.shape[0] + 5  # 起始行
    col_list = ['Name', '遲到次數', '遲到分鐘', '早退次數', '早退分鐘', '上月剩餘休假', '本月休假天數',
                '本月剩餘休假', '上月剩餘年假', '本月年假天數', '本月剩餘年假', '本月加班時長']
    for index1, title1 in enumerate(col_list):
        worksheet1.write(row_nums, index1, title1, format1)
    row_nums += 1  # 起始行
    for index11, row2 in books.iterrows():
        for index21, rowstr in enumerate(row2):
            if str(rowstr) == 'nan':
                worksheet1.write(index11 + row_nums, index21, '', format1)
            elif str(rowstr) == 'NaN':
                worksheet1.write(index11 + row_nums, index21, '', format1)
            else:
                worksheet1.write(index11 + row_nums, index21, rowstr, format1)

    worksheet1.set_default_row(21)  # 默认设置所有行高的高度
    worksheet1.set_column("A:A", 10)
    worksheet1.set_column("B:N", 11)
    worksheet1.set_column("C:C", 6)
    worksheet1.set_column("E:E", 6)
    worksheet1.set_column("G:G", 6)
    worksheet1.set_column("I:I", 6)
    worksheet1.set_column("K:K", 6)
    worksheet1.set_column("M:M", 6)
    worksheet1.set_column("O:O", 6)


def _roster_has_sheet(path, sheet):
    try:
        names = pd.ExcelFile(path).sheet_names
    except Exception as exc:
        print("skip unreadable", path, exc)
        return False
    if sheet not in names:
        print("skip, no sheet", sheet, path)
        return False
    return True


def _close_writer():
    """The last workbook stays open in this process until it is closed."""
    current = globals().get("writer")
    if current is None:
        return
    try:
        current.close()
    except Exception:
        pass
    globals()["writer"] = None


def _swap_in(temp, dest):
    """Replace dest. Windows refuses while Excel or Drive still has it open."""
    import time
    error = None
    for _ in range(10):
        try:
            os.replace(temp, dest)
            return
        except PermissionError as exc:
            error = exc
            time.sleep(0.3)
    raise SystemExit(f"請先關閉 Excel 中的 {dest.name}，然後再按重新檢查。") from error


def run_attendance(csv_path, roster_root, sheet, out_path, facts_path=None):
    """Write the attendance workbook and return per-day facts."""
    global file_path1, month_sheet, writer, workbook, location, FACTS
    file_path1 = str(csv_path)
    month_sheet = sheet
    FACTS = []
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _close_writer()
    temp = out_path.with_name(out_path.stem + "._new.xlsx")
    if temp.exists():
        try:
            temp.unlink()
        except PermissionError:
            temp = out_path.with_name(out_path.stem + "._new2.xlsx")

    writer = pd.ExcelWriter(temp, engine="xlsxwriter")
    workbook = writer.book
    roster_root = Path(roster_root)
    for root1, dirs, files in os.walk(roster_root):
        dirs.sort()
        for dir1 in dirs:
            dir_path = os.path.join(root1, dir1)
            location = dir1
            for file_path2 in sorted(Path(dir_path).iterdir(), key=lambda p: p.name):
                if ".xls" in str(file_path2) and "~$" not in str(file_path2):
                    if not _roster_has_sheet(file_path2, sheet):
                        continue
                    print(dir1, file_path2)
                    books, datas = datapro(file_path2, FACTS)
                    data_save(books, datas)
    writer.close()
    writer = None
    _swap_in(temp, out_path)

    facts = pd.DataFrame(FACTS)
    if facts_path is not None:
        facts_path = Path(facts_path)
        facts_temp = facts_path.with_name(facts_path.stem + "._new.xlsx")
        facts.to_excel(facts_temp, index=False)
        _swap_in(facts_temp, facts_path)
    return facts


if __name__ == "__main__":
    from payroll.core.config import parse_month
    info = parse_month("2026-10")
    run_attendance(
        info["daka"], info["rosters"], info["sheet"],
        info["system"] / f"{info['sheet']}考勤核對表.xlsx",
        info["system"] / "daily_facts.xlsx",
    )






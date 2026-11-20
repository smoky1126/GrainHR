/**
 * 把店鋪更表複製成 Excel，薪酬系統就可以從 Google Drive 讀取。
 *
 * 店鋪繼續用 Google 試算表。這個指令碼把 Excel 副本存到
 * 共用雲端硬碟 HR System/_payroll_copies。每位人事的電腦都會同步到，
 * 薪酬系統只讀副本。出糧的電腦不用登入 Google。
 * 執行腳本的帳戶要是 HR System 的成員，而且要有編輯權限。
 *
 * 只需設定一次：
 * 1. 用可以編輯 Shop Admin 的帳戶打開 https://script.google.com 。
 * 2. 新增專案，貼上這個檔案，儲存。
 * 3. 在 copyRosters 按「執行」，然後允許。
 * 4. 觸發條件（時鐘圖示）：copyRosters，時間驅動，每小時。
 *
 * 想立即更新，打開專案再按「執行」。
 * 資料夾和檔案名稱要同 payroll/config.py 的 ROSTER_SOURCES 一致。
 */

var MONTH_TOKEN = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
var XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
var SHEET_MIME = "application/vnd.google-apps.spreadsheet";

var ROSTER_SOURCES = [
  ["BG 新蒲崗工場", "3F_BG_roaster_{year}_{mon}", "3F_Bread"],
  ["MD Pastry", "MD_roaster_{year}_{mon}", "3F_Pastry"],
  ["Office", "Office BG roaster_{year}_{mon}", "11F"],
];

(function addShops() {
  ["JD", "TKS", "TW", "WC"].forEach(function (shop) {
    ROSTER_SOURCES.push(["Bread/" + shop, shop + "_Bread_roaster_{year}_{mon}", shop + "_Bread"]);
  });
  ["HKU", "JD", "TKS", "TW", "WC"].forEach(function (shop) {
    ROSTER_SOURCES.push(["Retail/" + shop, shop + "_Retail_roaster_{year}_{mon}", shop + "_Retail"]);
  });
})();

function copyRosters() {
  var root = rosterRoot();
  var copyRoot = hrCopyRoot();
  var lines = ["已複製 " + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd HH:mm")];
  monthsToCopy().forEach(function (when) {
    var token = MONTH_TOKEN[when.month];
    ROSTER_SOURCES.forEach(function (source) {
      var folderPath = source[0];
      var fileName = source[1].replace("{year}", String(when.year)).replace("{mon}", token);
      var shop = source[2];
      try {
        lines.push(copyOne(root, copyRoot, folderPath, fileName, shop));
      } catch (error) {
        lines.push("問題 " + shop + " " + fileName + "：" + error);
      }
    });
  });
  var stamp = copyRoot.getFilesByName("_copied_at.txt");
  var text = lines.join("\n") + "\n";
  if (stamp.hasNext()) {
    stamp.next().setContent(text);
  } else {
    copyRoot.createFile("_copied_at.txt", text);
  }
}

function monthsToCopy() {
  var now = new Date();
  var previous = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return [
    {year: now.getFullYear(), month: now.getMonth() + 1},
    {year: previous.getFullYear(), month: previous.getMonth() + 1},
  ];
}

function copyOne(root, copyRoot, folderPath, fileName, shop) {
  var sourceFolder = walkFolders(root, folderPath);
  if (!sourceFolder) {
    return "找不到 " + shop + " " + fileName + "：沒有資料夾 " + folderPath;
  }
  var found = sourceFolder.getFilesByName(fileName);
  var source = null;
  var count = 0;
  while (found.hasNext()) {
    source = found.next();
    count += 1;
  }
  if (count === 0) {
    return "找不到 " + shop + " " + fileName;
  }
  if (count > 1) {
    return "問題 " + shop + " " + fileName + "：多於一份同名檔案";
  }
  var shopFolder = folderNamed(copyRoot, shop, true);
  var downloadName = fileName + ".xlsx";
  if (unchanged(source, shopFolder, downloadName)) {
    return "完成 " + shop + " " + fileName + " 未有更改";
  }
  writeCopy(shopFolder, downloadName, asXlsx(source, downloadName));
  return "完成 " + shop + " " + fileName;
}

function unchanged(source, folder, downloadName) {
  var files = folder.getFilesByName(downloadName);
  var newest = null;
  while (files.hasNext()) {
    var file = files.next();
    if (!newest || file.getLastUpdated().getTime() > newest.getLastUpdated().getTime()) {
      newest = file;
    }
  }
  return newest && newest.getLastUpdated().getTime() >= source.getLastUpdated().getTime();
}

function asXlsx(file, downloadName) {
  if (file.getMimeType() !== SHEET_MIME) {
    return file.getBlob().setName(downloadName);
  }
  var url = "https://www.googleapis.com/drive/v3/files/" + file.getId()
    + "/export?mimeType=" + encodeURIComponent(XLSX_MIME);
  var response = UrlFetchApp.fetch(url, {
    headers: {Authorization: "Bearer " + ScriptApp.getOAuthToken()},
    muteHttpExceptions: true,
  });
  if (response.getResponseCode() !== 200) {
    throw new Error("Excel 匯出失敗（" + response.getResponseCode() + "）");
  }
  return response.getBlob().setName(downloadName);
}

function writeCopy(folder, downloadName, blob) {
  var files = folder.getFilesByName(downloadName);
  while (files.hasNext()) {
    files.next().setTrashed(true);
  }
  folder.createFile(blob);
}

function hrCopyRoot() {
  var folders = DriveApp.getFoldersByName("HR System");
  var match = null;
  var count = 0;
  while (folders.hasNext()) {
    match = folders.next();
    count += 1;
  }
  if (count > 1) {
    throw new Error("多於一個名為 HR System 的資料夾。");
  }
  if (count === 0) {
    throw new Error("這個帳戶打不開共用雲端硬碟 HR System。請把帳戶加進去，並給編輯權限。");
  }
  return folderNamed(match, "_payroll_copies", true);
}

function rosterRoot() {
  var admins = DriveApp.getFoldersByName("Shop Admin");
  while (admins.hasNext()) {
    var rosters = admins.next().getFoldersByName("Roster");
    if (rosters.hasNext()) {
      return rosters.next();
    }
  }
  throw new Error("這個帳戶打不開 Shop Admin/Roster。");
}

function walkFolders(parent, relative) {
  var current = parent;
  var parts = relative.split("/");
  for (var index = 0; index < parts.length; index++) {
    var children = current.getFoldersByName(parts[index]);
    if (!children.hasNext()) {
      return null;
    }
    current = children.next();
    if (children.hasNext()) {
      throw new Error("多於一個名為 " + parts[index] + " 的資料夾");
    }
  }
  return current;
}

function folderNamed(parent, name, create) {
  var found = parent.getFoldersByName(name);
  if (found.hasNext()) {
    var folder = found.next();
    if (found.hasNext()) {
      throw new Error("多於一個名為 " + name + " 的資料夾");
    }
    return folder;
  }
  if (!create) {
    return null;
  }
  return parent.createFolder(name);
}

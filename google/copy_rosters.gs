/**
 * Copy each shop roster to Excel so GrainHR can read it from Drive.
 *
 * Folder names are not in this file. In the Apps Script project settings,
 * add a script property named GRAINHR_COPY. Its value is JSON:
 * {
 *   "drive": "Shared drive name",
 *   "folders": ["parent folder", "app folder"],
 *   "inbox": "roster_inbox",
 *   "rosterRoot": ["Roster parent", "Roster"],
 *   "sources": [["folder", "file_{year}_{mon}", "shop code"]],
 *   "bread": ["S1"],
 *   "retail": ["S1"]
 * }
 * Copy that JSON from the private company file. Do not commit it.
 *
 * The account that runs the script needs edit access to the roster sheets.
 * Trigger: copyRosters, time-driven, every hour.
 */

var MONTH_TOKEN = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
var XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
var SHEET_MIME = "application/vnd.google-apps.spreadsheet";

function copyConfig() {
  var raw = PropertiesService.getScriptProperties().getProperty("GRAINHR_COPY");
  if (!raw) {
    throw new Error("Set the script property GRAINHR_COPY. This file has no folder names.");
  }
  return JSON.parse(raw);
}

function rosterSources(config) {
  var sources = (config.sources || []).slice();
  (config.bread || []).forEach(function (shop) {
    sources.push(["Bread/" + shop, shop + "_Bread_roaster_{year}_{mon}", shop + "_Bread"]);
  });
  (config.retail || []).forEach(function (shop) {
    sources.push(["Retail/" + shop, shop + "_Retail_roaster_{year}_{mon}", shop + "_Retail"]);
  });
  return sources;
}

function copyRosters() {
  var config = copyConfig();
  var root = rosterRoot(config);
  var copyRoot = hrCopyRoot(config);
  var lines = ["已複製 " + Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd HH:mm")];
  monthsToCopy().forEach(function (when) {
    var token = MONTH_TOKEN[when.month];
    rosterSources(config).forEach(function (source) {
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
  return "完成 " + shop + " " + fileName + " 已重新匯出";
}

function unchanged(source, folder, downloadName) {
  // Cell edits in a Google Sheet often leave getLastUpdated() unchanged, so the
  // old check kept exporting yesterday's Excel. Always export a Sheet again.
  if (source.getMimeType() === SHEET_MIME) {
    return false;
  }
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

function hrCopyRoot(config) {
  var match = sharedDriveRoot(config.drive);
  if (!match) {
    throw new Error("找不到共用雲端硬碟。在 Apps Script 左側「服務」加 Drive API，然後再執行。");
  }
  var current = match;
  (config.folders || []).forEach(function (name) {
    var next = folderNamed(current, name, false);
    if (!next) {
      throw new Error("找不到資料夾 " + name);
    }
    current = next;
  });
  var data = folderNamed(current, "data", true);
  return folderNamed(data, config.inbox || "roster_inbox", true);
}

function sharedDriveRoot(name) {
  if (typeof Drive === "undefined" || !Drive.Drives) {
    return null;
  }
  var pageToken = null;
  do {
    var response = Drive.Drives.list({pageSize: 100, pageToken: pageToken});
    var drives = response.drives || response.items || [];
    for (var i = 0; i < drives.length; i++) {
      if (drives[i].name === name) {
        return DriveApp.getFolderById(drives[i].id);
      }
    }
    pageToken = response.nextPageToken;
  } while (pageToken);
  return null;
}

function rosterRoot(config) {
  var names = config.rosterRoot || [];
  if (!names.length) {
    throw new Error("GRAINHR_COPY 沒有 rosterRoot。");
  }
  var parents = DriveApp.getFoldersByName(names[0]);
  while (parents.hasNext()) {
    var current = parents.next();
    var found = true;
    for (var index = 1; index < names.length; index++) {
      var children = current.getFoldersByName(names[index]);
      if (!children.hasNext()) {
        found = false;
        break;
      }
      current = children.next();
    }
    if (found) {
      return current;
    }
  }
  throw new Error("這個帳戶打不開更表資料夾。");
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

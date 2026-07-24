const CONFIG = {
  sourceSheetName: 'Накладная',
  targetSheetName: 'Загрузка тест',
  productSheetName: 'Товары',
  aliasSheetName: 'Сопоставление Товаров',
  newProductsSheetName: 'Новые товары',
  newProductsForUcSheetName: 'Новые товары для УС',
  packagingRulesSheetName: 'Правила фасовок',
  headerRow: 2,
  startRow: 3,
  aliasHeaderRow: 3,
  newProductsHeaderRow: 2,
  packagingRulesHeaderRow: 2,
  productSuggestionLimit: 10,
};

const LOAD_STATUS = {
  CHECK: 'Проверить',
  READY: 'Загрузить',
  LOADED: 'Загружено',
  NOT_READY: 'Не готово',
  REVIEW: 'Требует проверки',
};

const ROW_STATUS = {
  RECOGNIZED: 'Распознано',
  MANUAL: 'Правка вручную',
  ERROR: 'Ошибка загрузки',
  READY: 'Готов к загрузке',
  SENT: 'Отправлено в УС',
  RETURN: 'Возврат на проверку',
};

const PRODUCT_MATCH_STATUS = {
  FOUND: 'Товар найден',
  NEED_CHOICE: 'Требует выбора товара УС',
  NEW: 'Новый товар',
  WAIT_CREATE: 'Ожидает создания в УС',
  MANUAL: 'Сопоставлен вручную',
  SKIP: 'Не загружать',
};

const COLORS = {
  ready: '#d9ead3',
  notReady: '#f4cccc',
  loaded: '#cfe2f3',
  review: '#fff2cc',
  check: '#eeeeee',
  returnReview: '#fce5cd',
  empty: '#ffffff',
};

const MANUAL_CORRECTIONS = ['Нет в справочнике', 'Исключение', 'Другое', 'Сопоставление', 'Фасовка'];

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Проверка / Загрузка')
    .addItem('Сопоставить товары', 'matchSelectedDocuments')
    .addItem('Обновить варианты товаров УС', 'refreshNewProductChoices')
    .addItem('Вернуть выбранный товар на сопоставление', 'returnActiveProductToMatching')
    .addItem('Применить решения по новым товарам', 'applyNewProductDecisions')
    .addItem('Подготовить новые товары для УС', 'prepareNewProductsForUc')
    .addItem('Связать созданные товары из справочника', 'linkCreatedProductsFromDirectory')
    .addSeparator()
    .addItem('Сформировать черновики правил фасовок', 'suggestPackagingRulesForSelectedDocuments')
    .addItem('Активировать выбранные черновики фасовок', 'activateSelectedPackagingRuleDrafts')
    .addItem('Применить правила фасовок', 'applyPackagingRulesToSelectedDocuments')
    .addItem('Сохранить ручной сухой вес как правило', 'saveManualDryWeightsAsPackagingRules')
    .addItem('Проверить выбранные документы', 'checkSelectedDocuments')
    .addItem('Обновить все статусы', 'checkReadinessByStatus')
    .addSeparator()
    .addItem('Загрузить на тестовый лист', 'loadSelectedDocumentsToTestSheet')
    .addItem('Вернуть на проверку', 'returnSelectedDocumentsToReview')
    .addSeparator()
    .addItem('Восстановить форматы чисел', 'restoreInvoiceNumberFormats')
    .addToUi();
}

function onEdit(event) {
  if (!event || !event.range || event.range.getNumRows() !== 1 || event.range.getNumColumns() !== 1) {
    return;
  }

  const editedSheet = event.range.getSheet();

  if (editedSheet.getName() !== CONFIG.newProductsSheetName || event.range.getRow() <= CONFIG.newProductsHeaderRow) {
    return;
  }

  try {
    applySelectedProductFromDropdown_(event);
  } catch (error) {
    const spreadsheet = event.source || SpreadsheetApp.getActiveSpreadsheet();
    spreadsheet.toast('Не удалось заполнить товар УС: ' + error.message, 'АвтоСнаб', 6);
  }
}

function refreshNewProductChoices() {
  const result = refreshNewProductChoices_(SpreadsheetApp.getActiveSpreadsheet());
  let message = 'Варианты товаров УС обновлены. Строк с вариантами: ' + result.rowsWithChoices;

  if (result.rowsWithoutChoices > 0) {
    message += '\nБез подходящих вариантов: ' + result.rowsWithoutChoices;
  }

  SpreadsheetApp.getUi().alert(message);
}

function returnActiveProductToMatching() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getActiveSheet();

  if (!sheet || sheet.getName() !== CONFIG.sourceSheetName) {
    SpreadsheetApp.getUi().alert('Сначала выбери ошибочно сопоставленную строку на листе "Накладная".');
    return;
  }

  const activeRange = sheet.getActiveRange();
  const activeRow = activeRange ? activeRange.getRow() : 0;

  if (activeRow < CONFIG.startRow) {
    SpreadsheetApp.getUi().alert('Выбери товарную строку на листе "Накладная".');
    return;
  }

  const columns = getColumnMap_(sheet);
  requireBaseColumns_(columns);
  requireColumns_(columns, [
    'ID документа',
    'ID строки',
    'ИНН Поставщика',
    'Наименование товара из документа',
    'Ед.изм. в документе',
  ]);

  const values = sheet
    .getRange(CONFIG.startRow, 1, activeRow - CONFIG.startRow + 1, sheet.getLastColumn())
    .getValues();
  const selectedRow = values[values.length - 1];
  let documentStartIndex = 0;

  values.forEach((row, index) => {
    const hasDocumentStart =
      row[columns['Дата документа'] - 1] !== '' ||
      row[columns['№ Документа'] - 1] !== '' ||
      row[columns['Поставщик'] - 1] !== '' ||
      row[columns['ID документа'] - 1] !== '';

    if (hasDocumentStart) {
      documentStartIndex = index;
    }
  });

  const firstRow = values[documentStartIndex];
  const documentId = String(firstRow[columns['ID документа'] - 1]).trim();
  const lineId = String(selectedRow[columns['ID строки'] - 1]).trim();
  const supplier = String(firstRow[columns['Поставщик'] - 1]).trim();
  const supplierInn = String(firstRow[columns['ИНН Поставщика'] - 1]).trim();
  const originalName = String(selectedRow[columns['Наименование товара из документа'] - 1]).trim();
  const normalizedName = normalizeProductName_(originalName);
  const documentUnit = String(selectedRow[columns['Ед.изм. в документе'] - 1]).trim();
  const suggestedProductName = String(selectedRow[columns['Наименование товара в УС'] - 1]).trim();

  if (lineId === '' || originalName === '') {
    SpreadsheetApp.getUi().alert('В выбранной строке не найдены ID строки или наименование товара из документа.');
    return;
  }

  const context = buildProductMatchingContext_(spreadsheet);
  const aliasesMarked = markAliasesForReview_(
    context,
    supplier,
    supplierInn,
    originalName,
    normalizedName
  );

  sheet.getRange(activeRow, columns['Код товара УС']).clearContent();
  sheet.getRange(activeRow, columns['Статус сопоставления товара']).setValue(PRODUCT_MATCH_STATUS.NEED_CHOICE);
  sheet.getRange(activeRow, columns['Корректировка']).setValue('Сопоставление');

  const reopened = reopenNewProductQueueRow_(
    context,
    documentId,
    lineId,
    originalName,
    suggestedProductName
  );
  let added = false;

  if (!reopened) {
    added = addNewProductQueueRowIfNeeded_(
      context,
      documentId,
      lineId,
      supplier,
      supplierInn,
      originalName,
      normalizedName,
      documentUnit,
      suggestedProductName,
      PRODUCT_MATCH_STATUS.NEED_CHOICE
    );
  }

  refreshNewProductChoices_(spreadsheet);

  SpreadsheetApp.getUi().alert(
    'Товар возвращен на сопоставление.' +
      '\nАлиасов отправлено на проверку: ' +
      aliasesMarked +
      '\nСтрока в "Новые товары": ' +
      (reopened ? 'открыта повторно' : added ? 'добавлена' : 'уже существует')
  );
}

function applyNewProductDecisions() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const invoiceSheet = spreadsheet.getSheetByName(CONFIG.sourceSheetName);
  const newProductsSheet = spreadsheet.getSheetByName(CONFIG.newProductsSheetName);

  if (!invoiceSheet) {
    throw new Error('Не найден лист: ' + CONFIG.sourceSheetName);
  }

  if (!newProductsSheet) {
    throw new Error('Не найден лист: ' + CONFIG.newProductsSheetName);
  }

  const invoiceColumns = getColumnMap_(invoiceSheet);
  const newProductColumns = getColumnMapByHeaderRow_(newProductsSheet, CONFIG.newProductsHeaderRow);
  const context = buildProductMatchingContext_(spreadsheet);

  requireBaseColumns_(invoiceColumns);
  requireColumns_(invoiceColumns, ['ID документа', 'ID строки']);
  requireColumns_(newProductColumns, [
    'ID документа',
    'ID строки',
    'Поставщик',
    'ИНН поставщика',
    'Название из документа',
    'Нормализованное название',
    'Ед. изм. из документа',
    'Решение пользователя',
    'Статус нового товара',
    'Наименование товара в УС',
    'Код товара УС',
    'Ед. изм. в УС',
  ]);

  const invoiceRowIndex = buildInvoiceRowIndex_(invoiceSheet, invoiceColumns);
  const lastRow = newProductsSheet.getLastRow();

  if (lastRow <= CONFIG.newProductsHeaderRow) {
    SpreadsheetApp.getUi().alert('На листе "Новые товары" нет строк для применения.');
    return;
  }

  const invoiceData = getActualData_(invoiceSheet, invoiceColumns);

  if (invoiceData.values.length === 0) {
    SpreadsheetApp.getUi().alert('На листе "Накладная" нет строк для применения решений.');
    return;
  }

  const invoiceDocuments = getDocumentBlocks_(invoiceData.values, invoiceColumns);
  const selectedDocuments = invoiceDocuments.filter((document) => {
    const firstRow = invoiceData.values[document.startIndex];
    return firstRow[invoiceColumns['Загрузка'] - 1] === true;
  });

  if (selectedDocuments.length === 0) {
    SpreadsheetApp.getUi().alert('Отметь галочкой документ, для которого нужно применить решения по товарам.');
    return;
  }

  const selectedLineKeys = {};

  selectedDocuments.forEach((document) => {
    let currentDocumentId = '';

    for (let rowIndex = document.startIndex; rowIndex <= document.endIndex; rowIndex += 1) {
      const invoiceRow = invoiceData.values[rowIndex];
      const rowDocumentId = String(invoiceRow[invoiceColumns['ID документа'] - 1]).trim();
      const lineId = String(invoiceRow[invoiceColumns['ID строки'] - 1]).trim();

      if (rowDocumentId !== '') {
        currentDocumentId = rowDocumentId;
      }

      if (currentDocumentId !== '' && lineId !== '') {
        selectedLineKeys[currentDocumentId + '|' + lineId] = true;
      }
    }
  });

  const values = newProductsSheet
    .getRange(CONFIG.newProductsHeaderRow + 1, 1, lastRow - CONFIG.newProductsHeaderRow, newProductsSheet.getLastColumn())
    .getValues();

  let appliedCount = 0;
  let preparedCount = 0;
  let skippedCount = 0;
  const skippedMessages = [];
  const rowsToPrepare = [];

  values.forEach((row, index) => {
    const sheetRow = CONFIG.newProductsHeaderRow + 1 + index;
    const decision = String(row[newProductColumns['Решение пользователя'] - 1]).trim();
    const status = String(row[newProductColumns['Статус нового товара'] - 1]).trim();
    let productName = String(row[newProductColumns['Наименование товара в УС'] - 1]).trim();
    let productCode = String(row[newProductColumns['Код товара УС'] - 1]).trim();
    let selectedProductUnit = String(row[newProductColumns['Ед. изм. в УС'] - 1]).trim();
    const documentId = String(row[newProductColumns['ID документа'] - 1]).trim();
    const lineId = String(row[newProductColumns['ID строки'] - 1]).trim();
    const originalName = String(row[newProductColumns['Название из документа'] - 1]).trim();

    if (!selectedLineKeys[documentId + '|' + lineId]) {
      return;
    }

    if (status === 'Сопоставлен') {
      return;
    }

    if (decision !== 'Сопоставить') {
      return;
    }

    const selectedProduct = resolveProductSelection_(context.productList, productName, selectedProductUnit);

    if (selectedProduct) {
      productName = selectedProduct.name;
      productCode = selectedProduct.code;
      selectedProductUnit = selectedProduct.unit;
      newProductsSheet.getRange(sheetRow, newProductColumns['Наименование товара в УС']).setValue(productName);
      newProductsSheet.getRange(sheetRow, newProductColumns['Код товара УС']).setValue(productCode);
      newProductsSheet.getRange(sheetRow, newProductColumns['Ед. изм. в УС']).setValue(selectedProductUnit);
      newProductsSheet.getRange(sheetRow, newProductColumns['Наименование товара в УС']).clearDataValidations();
    }

    if (productName === '') {
      skippedCount += 1;
      skippedMessages.push('строка ' + sheetRow + ': не заполнено наименование товара УС');
      return;
    }

    if (productCode === '') {
      if (selectedProductUnit === '') {
        skippedCount += 1;
        skippedMessages.push('строка ' + sheetRow + ': для нового товара не заполнена ед. изм. в УС');
        return;
      }

      rowsToPrepare.push({
        sheetRow: sheetRow,
        productName: productName,
      });
      return;
    }

    const invoiceRowNumber = findInvoiceRowNumber_(invoiceRowIndex, documentId, lineId, originalName);

    if (!invoiceRowNumber) {
      skippedCount += 1;
      skippedMessages.push('строка ' + sheetRow + ': не найдена строка накладной по ID');
      return;
    }

    const supplier = String(row[newProductColumns['Поставщик'] - 1]).trim();
    const supplierInn = String(row[newProductColumns['ИНН поставщика'] - 1]).trim();
    const normalizedName = String(row[newProductColumns['Нормализованное название'] - 1]).trim() || normalizeProductName_(originalName);
    const documentUnit = String(row[newProductColumns['Ед. изм. из документа'] - 1]).trim();
    const productByCode = context.productCodeIndex[productCode] || null;
    const productUnit = productByCode && productByCode.unit !== '' ? productByCode.unit : selectedProductUnit;

    writeProductMatchToInvoice_(
      invoiceSheet,
      invoiceColumns,
      invoiceRowNumber,
      productName,
      productCode,
      productUnit,
      PRODUCT_MATCH_STATUS.MANUAL
    );

    invoiceSheet.getRange(invoiceRowNumber, invoiceColumns['Корректировка']).clearContent().setBackground(COLORS.empty);

    appendAliasIfNeeded_(
      context,
      supplier,
      supplierInn,
      originalName,
      normalizedName,
      documentUnit,
      productName,
      productCode,
      productUnit,
      'Выбрано пользователем'
    );

    newProductsSheet.getRange(sheetRow, newProductColumns['Статус нового товара']).setValue('Сопоставлен');
    appliedCount += 1;
  });

  if (rowsToPrepare.length > 0) {
    const productNames = uniqueValues_(rowsToPrepare.map((item) => item.productName));
    const previewNames = productNames.slice(0, 10);
    let confirmationText =
      'Не найдены в справочнике "Товары": ' +
      rowsToPrepare.length +
      '\n\n' +
      previewNames.join('\n');

    if (productNames.length > previewNames.length) {
      confirmationText += '\n...и еще ' + (productNames.length - previewNames.length);
    }

    confirmationText += '\n\nПодготовить эти товары к созданию в УС?';

    const confirmation = SpreadsheetApp.getUi().alert(
      'Новые товары',
      confirmationText,
      SpreadsheetApp.getUi().ButtonSet.YES_NO
    );

    if (confirmation === SpreadsheetApp.getUi().Button.YES) {
      rowsToPrepare.forEach((item) => {
        const decisionCell = newProductsSheet.getRange(item.sheetRow, newProductColumns['Решение пользователя']);
        setPrepareCreateDecision_(decisionCell);
        newProductsSheet.getRange(item.sheetRow, newProductColumns['Статус нового товара']).setValue('Новый');
        newProductsSheet
          .getRange(item.sheetRow, newProductColumns['Наименование товара в УС'])
          .clearDataValidations();
      });

      preparedCount = rowsToPrepare.length;
    } else {
      skippedCount += rowsToPrepare.length;
      skippedMessages.push('не подтверждена подготовка новых товаров: ' + rowsToPrepare.length);
    }
  }

  let message =
    'Применение решений завершено. Сопоставлено строк: ' +
    appliedCount +
    '\nВыбрано документов: ' +
    selectedDocuments.length;

  if (preparedCount > 0) {
    message += '\nПодготовлены к созданию: ' + preparedCount;
  }

  if (skippedCount > 0) {
    message += '\n\nПропущено строк: ' + skippedCount + '\n' + skippedMessages.join('\n');
  }

  SpreadsheetApp.getUi().alert(message);
}

function prepareNewProductsForUc() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const invoiceSheet = spreadsheet.getSheetByName(CONFIG.sourceSheetName);
  const newProductsSheet = spreadsheet.getSheetByName(CONFIG.newProductsSheetName);

  if (!invoiceSheet) {
    throw new Error('Не найден лист: ' + CONFIG.sourceSheetName);
  }

  if (!newProductsSheet) {
    throw new Error('Не найден лист: ' + CONFIG.newProductsSheetName);
  }

  const invoiceColumns = getColumnMap_(invoiceSheet);
  const newProductColumns = getColumnMapByHeaderRow_(newProductsSheet, CONFIG.newProductsHeaderRow);

  requireBaseColumns_(invoiceColumns);
  requireColumns_(newProductColumns, [
    'ID нового товара',
    'ID документа',
    'ID строки',
    'Поставщик',
    'ИНН поставщика',
    'Название из документа',
    'Нормализованное название',
    'Ед. изм. из документа',
    'Предлагаемое название УС',
    'Ед. изм. в УС',
    'Решение пользователя',
    'Статус нового товара',
    'Наименование товара в УС',
    'Код товара УС',
  ]);

  const lastRow = newProductsSheet.getLastRow();

  if (lastRow <= CONFIG.newProductsHeaderRow) {
    SpreadsheetApp.getUi().alert('На листе "Новые товары" нет строк для подготовки.');
    return;
  }

  const values = newProductsSheet
    .getRange(CONFIG.newProductsHeaderRow + 1, 1, lastRow - CONFIG.newProductsHeaderRow, newProductsSheet.getLastColumn())
    .getValues();
  const invoiceData = getActualData_(invoiceSheet, invoiceColumns);

  if (invoiceData.values.length === 0) {
    SpreadsheetApp.getUi().alert('На листе "Накладная" нет строк для подготовки новых товаров.');
    return;
  }

  const invoiceDocuments = getDocumentBlocks_(invoiceData.values, invoiceColumns);
  const selectedDocuments = invoiceDocuments.filter((document) => {
    const firstRow = invoiceData.values[document.startIndex];
    return firstRow[invoiceColumns['Загрузка'] - 1] === true;
  });

  if (selectedDocuments.length === 0) {
    SpreadsheetApp.getUi().alert('Отметь галочкой документ, для которого нужно подготовить новые товары.');
    return;
  }

  const selectedLineKeys = {};

  selectedDocuments.forEach((document) => {
    let currentDocumentId = '';

    for (let rowIndex = document.startIndex; rowIndex <= document.endIndex; rowIndex += 1) {
      const invoiceRow = invoiceData.values[rowIndex];
      const rowDocumentId = String(invoiceRow[invoiceColumns['ID документа'] - 1]).trim();
      const lineId = String(invoiceRow[invoiceColumns['ID строки'] - 1]).trim();

      if (rowDocumentId !== '') {
        currentDocumentId = rowDocumentId;
      }

      if (currentDocumentId !== '' && lineId !== '') {
        selectedLineKeys[currentDocumentId + '|' + lineId] = true;
      }
    }
  });

  const invoiceRowIndex = buildInvoiceRowIndex_(invoiceSheet, invoiceColumns);
  const exportByKey = {};
  const sourceRowsToMark = [];
  const invoiceRowsToMark = [];
  const skippedMessages = [];

  values.forEach((row, index) => {
    const sheetRow = CONFIG.newProductsHeaderRow + 1 + index;
    const documentId = String(row[newProductColumns['ID документа'] - 1]).trim();
    const lineId = String(row[newProductColumns['ID строки'] - 1]).trim();

    if (!selectedLineKeys[documentId + '|' + lineId]) {
      return;
    }

    const decision = String(row[newProductColumns['Решение пользователя'] - 1]).trim();
    const status = String(row[newProductColumns['Статус нового товара'] - 1]).trim();
    const productCode = String(row[newProductColumns['Код товара УС'] - 1]).trim();

    if (!isPrepareCreateDecision_(decision)) {
      return;
    }

    if (status === 'Сопоставлен') {
      return;
    }

    if (productCode !== '') {
      skippedMessages.push('строка ' + sheetRow + ': код товара УС уже заполнен, лучше выбрать решение "Сопоставить"');
      return;
    }

    const newProductId = String(row[newProductColumns['ID нового товара'] - 1]).trim();
    const supplier = String(row[newProductColumns['Поставщик'] - 1]).trim();
    const supplierInn = String(row[newProductColumns['ИНН поставщика'] - 1]).trim();
    const originalName = String(row[newProductColumns['Название из документа'] - 1]).trim();
    const normalizedName = String(row[newProductColumns['Нормализованное название'] - 1]).trim();
    const documentUnit = String(row[newProductColumns['Ед. изм. из документа'] - 1]).trim();
    const suggestedName = String(row[newProductColumns['Предлагаемое название УС'] - 1]).trim();
    const productName = String(row[newProductColumns['Наименование товара в УС'] - 1]).trim() || suggestedName;
    const productUnit = String(row[newProductColumns['Ед. изм. в УС'] - 1]).trim();
    const comment = newProductColumns['Комментарий']
      ? String(row[newProductColumns['Комментарий'] - 1]).trim()
      : '';

    if (productName === '' || productUnit === '') {
      skippedMessages.push('строка ' + sheetRow + ': нужно заполнить наименование товара в УС и ед. изм. в УС');
      return;
    }

    const exportKey = normalizeProductName_(productName) + '|' + productUnit;
    const lineRef = documentId + ' / ' + lineId;

    if (!exportByKey[exportKey]) {
      exportByKey[exportKey] = {
        date: new Date(),
        productName: productName,
        productUnit: productUnit,
        supplier: supplier,
        supplierInn: supplierInn,
        suggestedName: suggestedName,
        normalizedName: normalizedName,
        documentUnit: documentUnit,
        originalNames: [],
        newProductIds: [],
        lineRefs: [],
        comments: [],
      };
    }

    exportByKey[exportKey].originalNames.push(originalName);
    exportByKey[exportKey].newProductIds.push(newProductId);
    exportByKey[exportKey].lineRefs.push(lineRef);

    if (comment !== '') {
      exportByKey[exportKey].comments.push(comment);
    }

    sourceRowsToMark.push(sheetRow);

    const invoiceRowNumber = findInvoiceRowNumber_(invoiceRowIndex, documentId, lineId, originalName);

    if (invoiceRowNumber) {
      invoiceRowsToMark.push(invoiceRowNumber);
    }
  });

  const exportRows = Object.keys(exportByKey).map((key) => {
    const item = exportByKey[key];

    return [
      item.date,
      item.productName,
      item.productUnit,
      item.supplier,
      item.supplierInn,
      item.suggestedName,
      item.normalizedName,
      uniqueValues_(item.originalNames).join('\n'),
      item.documentUnit,
      uniqueValues_(item.newProductIds).join(', '),
      uniqueValues_(item.lineRefs).join('\n'),
      item.lineRefs.length,
      'Создать в УС',
      'Ожидает создания в УС',
      uniqueValues_(item.comments).join('\n'),
    ];
  });

  if (exportRows.length === 0) {
    let message = 'Нет новых товаров для подготовки к созданию в УС.';

    if (skippedMessages.length > 0) {
      message += '\n\nПропущено:\n' + skippedMessages.join('\n');
    }

    SpreadsheetApp.getUi().alert(message);
    return;
  }

  const exportSheet = getOrCreateSheet_(spreadsheet, CONFIG.newProductsForUcSheetName);
  const exportHeaders = [
    'Дата подготовки',
    'Наименование товара в УС',
    'Ед. изм. в УС',
    'Поставщик',
    'ИНН поставщика',
    'Предлагаемое название УС',
    'Нормализованное название',
    'Названия из документов',
    'Ед. изм. из документа',
    'ID новых товаров',
    'ID документа / ID строки',
    'Количество строк',
    'Действие',
    'Статус',
    'Комментарий',
  ];

  exportSheet.clear();
  exportSheet.getRange(1, 1, 1, exportHeaders.length).setValues([exportHeaders]);
  exportSheet.getRange(1, 1, 1, exportHeaders.length).setFontWeight('bold');
  exportSheet.getRange(2, 1, exportRows.length, exportHeaders.length).setValues(exportRows);
  exportSheet.autoResizeColumns(1, exportHeaders.length);
  exportSheet.getRange(2, 1, exportRows.length, 1).setNumberFormat('dd.mm.yyyy hh:mm');

  sourceRowsToMark.forEach((sheetRow) => {
    newProductsSheet.getRange(sheetRow, newProductColumns['Статус нового товара']).setValue('Ожидает создания в УС');
  });

  invoiceRowsToMark.forEach((sheetRow) => {
    invoiceSheet.getRange(sheetRow, invoiceColumns['Статус сопоставления товара']).setValue(PRODUCT_MATCH_STATUS.WAIT_CREATE);
    invoiceSheet.getRange(sheetRow, invoiceColumns['Корректировка']).setValue('Нет в справочнике');
  });

  let message =
    'Подготовлен список новых товаров для УС.' +
    '\nТоваров к созданию: ' +
    exportRows.length +
    '\nВыбрано документов: ' +
    selectedDocuments.length +
    '\nСвязанных строк накладных: ' +
    invoiceRowsToMark.length +
    '\n\nЛист: "' +
    CONFIG.newProductsForUcSheetName +
    '"';

  if (skippedMessages.length > 0) {
    message += '\n\nПропущено:\n' + skippedMessages.join('\n');
  }

  SpreadsheetApp.getUi().alert(message);
}

function linkCreatedProductsFromDirectory() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const invoiceSheet = spreadsheet.getSheetByName(CONFIG.sourceSheetName);
  const newProductsSheet = spreadsheet.getSheetByName(CONFIG.newProductsSheetName);
  const exportSheet = spreadsheet.getSheetByName(CONFIG.newProductsForUcSheetName);

  if (!invoiceSheet) {
    throw new Error('Не найден лист: ' + CONFIG.sourceSheetName);
  }

  if (!newProductsSheet) {
    throw new Error('Не найден лист: ' + CONFIG.newProductsSheetName);
  }

  if (!exportSheet) {
    SpreadsheetApp.getUi().alert('Сначала подготовь список новых товаров для УС.');
    return;
  }

  const invoiceColumns = getColumnMap_(invoiceSheet);
  const newProductColumns = getColumnMapByHeaderRow_(newProductsSheet, CONFIG.newProductsHeaderRow);
  const exportColumns = getColumnMapByHeaderRow_(exportSheet, 1);
  const context = buildProductMatchingContext_(spreadsheet);

  requireBaseColumns_(invoiceColumns);
  requireColumns_(newProductColumns, [
    'ID нового товара',
    'ID документа',
    'ID строки',
    'Поставщик',
    'ИНН поставщика',
    'Название из документа',
    'Нормализованное название',
    'Ед. изм. из документа',
    'Решение пользователя',
    'Статус нового товара',
    'Наименование товара в УС',
    'Код товара УС',
    'Ед. изм. в УС',
  ]);
  requireColumns_(exportColumns, ['ID новых товаров']);

  const exportLastRow = exportSheet.getLastRow();

  if (exportLastRow <= 1) {
    SpreadsheetApp.getUi().alert('На листе "' + CONFIG.newProductsForUcSheetName + '" нет товаров для связывания.');
    return;
  }

  const preparedNewProductIds = {};
  const exportValues = exportSheet
    .getRange(2, 1, exportLastRow - 1, exportSheet.getLastColumn())
    .getValues();

  exportValues.forEach((row) => {
    const rawIds = String(row[exportColumns['ID новых товаров'] - 1]).trim();

    rawIds.split(',').forEach((value) => {
      const newProductId = value.trim();

      if (newProductId !== '') {
        preparedNewProductIds[newProductId] = true;
      }
    });
  });

  const lastRow = newProductsSheet.getLastRow();

  if (lastRow <= CONFIG.newProductsHeaderRow) {
    SpreadsheetApp.getUi().alert('На листе "Новые товары" нет строк для связывания.');
    return;
  }

  const values = newProductsSheet
    .getRange(CONFIG.newProductsHeaderRow + 1, 1, lastRow - CONFIG.newProductsHeaderRow, newProductsSheet.getLastColumn())
    .getValues();
  const invoiceRowIndex = buildInvoiceRowIndex_(invoiceSheet, invoiceColumns);

  let linkedCount = 0;
  let skippedCount = 0;
  const skippedMessages = [];

  values.forEach((row, index) => {
    const sheetRow = CONFIG.newProductsHeaderRow + 1 + index;
    const newProductId = String(row[newProductColumns['ID нового товара'] - 1]).trim();

    if (!preparedNewProductIds[newProductId]) {
      return;
    }

    const decision = String(row[newProductColumns['Решение пользователя'] - 1]).trim();
    const status = String(row[newProductColumns['Статус нового товара'] - 1]).trim();

    if (status === 'Сопоставлен') {
      return;
    }

    if (status !== 'Ожидает создания в УС' && !isPrepareCreateDecision_(decision)) {
      return;
    }

    const productName = String(row[newProductColumns['Наименование товара в УС'] - 1]).trim();
    const selectedProductUnit = String(row[newProductColumns['Ед. изм. в УС'] - 1]).trim();
    const documentId = String(row[newProductColumns['ID документа'] - 1]).trim();
    const lineId = String(row[newProductColumns['ID строки'] - 1]).trim();

    if (productName === '') {
      skippedCount += 1;
      skippedMessages.push('строка ' + sheetRow + ': не заполнено наименование товара в УС');
      return;
    }

    const product = findProductByNameAndUnit_(context.productIndex, productName, selectedProductUnit);

    if (!product) {
      skippedCount += 1;
      skippedMessages.push('строка ' + sheetRow + ': товар не найден в листе "Товары" или найдено несколько вариантов');
      return;
    }

    const originalName = String(row[newProductColumns['Название из документа'] - 1]).trim();
    const invoiceRowNumber = findInvoiceRowNumber_(invoiceRowIndex, documentId, lineId, originalName);

    if (!invoiceRowNumber) {
      skippedCount += 1;
      skippedMessages.push('строка ' + sheetRow + ': не найдена строка накладной по ID');
      return;
    }

    const supplier = String(row[newProductColumns['Поставщик'] - 1]).trim();
    const supplierInn = String(row[newProductColumns['ИНН поставщика'] - 1]).trim();
    const normalizedName = String(row[newProductColumns['Нормализованное название'] - 1]).trim() || normalizeProductName_(originalName);
    const documentUnit = String(row[newProductColumns['Ед. изм. из документа'] - 1]).trim();

    newProductsSheet.getRange(sheetRow, newProductColumns['Наименование товара в УС']).setValue(product.name);
    newProductsSheet.getRange(sheetRow, newProductColumns['Код товара УС']).setValue(product.code);
    newProductsSheet.getRange(sheetRow, newProductColumns['Ед. изм. в УС']).setValue(product.unit);
    newProductsSheet.getRange(sheetRow, newProductColumns['Статус нового товара']).setValue('Сопоставлен');
    newProductsSheet.getRange(sheetRow, newProductColumns['Решение пользователя']).setValue('Сопоставить');

    writeProductMatchToInvoice_(
      invoiceSheet,
      invoiceColumns,
      invoiceRowNumber,
      product.name,
      product.code,
      product.unit,
      PRODUCT_MATCH_STATUS.MANUAL
    );

    invoiceSheet.getRange(invoiceRowNumber, invoiceColumns['Корректировка']).clearContent().setBackground(COLORS.empty);

    appendAliasIfNeeded_(
      context,
      supplier,
      supplierInn,
      originalName,
      normalizedName,
      documentUnit,
      product.name,
      product.code,
      product.unit,
      'Создано в УС'
    );

    linkedCount += 1;
  });

  let message = 'Связывание созданных товаров завершено. Сопоставлено строк: ' + linkedCount;

  if (skippedCount > 0) {
    message += '\n\nПропущено строк: ' + skippedCount + '\n' + skippedMessages.join('\n');
  }

  SpreadsheetApp.getUi().alert(message);
}

function matchSelectedDocuments() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(CONFIG.sourceSheetName);
  const columns = getColumnMap_(sheet);
  requireBaseColumns_(columns);

  const data = getActualData_(sheet, columns);

  if (data.values.length === 0) {
    SpreadsheetApp.getUi().alert('На листе нет строк для сопоставления.');
    return;
  }

  const documents = getDocumentBlocks_(data.values, columns);
  const selectedDocuments = documents.filter((document) => {
    const firstRow = data.values[document.startIndex];
    return firstRow[columns['Загрузка'] - 1] === true;
  });

  if (selectedDocuments.length === 0) {
    SpreadsheetApp.getUi().alert('Отметь галочкой документ, в котором нужно сопоставить товары.');
    return;
  }

  const context = buildProductMatchingContext_(spreadsheet);
  let matchedCount = 0;
  let unresolvedCount = 0;
  let newQueueCount = 0;

  selectedDocuments.forEach((document) => {
    const result = applyProductMatching_(sheet, data.values, columns, document, context);
    matchedCount += result.matchedCount;
    unresolvedCount += result.unresolvedCount;
    newQueueCount += result.newQueueCount;
  });

  const priceResult = calculateUsPricesForDocuments_(sheet, data.values, columns, selectedDocuments);

  const suggestionResult = refreshNewProductChoices_(spreadsheet);

  SpreadsheetApp.getUi().alert(
    'Сопоставление товаров завершено.' +
      '\nСопоставлено строк: ' +
      matchedCount +
      '\nТребуют выбора/решения: ' +
      unresolvedCount +
      '\nДобавлено в "Новые товары": ' +
      newQueueCount +
      '\nПодготовлены варианты выбора: ' +
      suggestionResult.rowsWithChoices +
      '\nРассчитано цен в УС: ' +
      priceResult.calculatedCount
  );
}

function applyPackagingRulesToSelectedDocuments() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(CONFIG.sourceSheetName);

  if (!sheet) {
    throw new Error('Не найден лист: ' + CONFIG.sourceSheetName);
  }

  const columns = getColumnMap_(sheet);
  requireBaseColumns_(columns);
  requirePackagingInvoiceColumns_(columns);

  const data = getActualData_(sheet, columns);

  if (data.values.length === 0) {
    SpreadsheetApp.getUi().alert('На листе нет строк для применения правил фасовок.');
    return;
  }

  const documents = getDocumentBlocks_(data.values, columns);
  const selectedDocuments = documents.filter((document) => {
    const firstRow = data.values[document.startIndex];
    return firstRow[columns['Загрузка'] - 1] === true;
  });

  if (selectedDocuments.length === 0) {
    SpreadsheetApp.getUi().alert('Отметь галочкой документ, для которого нужно применить правила фасовок.');
    return;
  }

  const result = applyPackagingRulesForDocuments_(
    spreadsheet,
    sheet,
    data.values,
    columns,
    selectedDocuments
  );
  const refreshedData = getActualData_(sheet, columns);
  const priceResult = calculateUsPricesForDocuments_(sheet, refreshedData.values, columns, selectedDocuments);

  SpreadsheetApp.getUi().alert(
    'Обработка фасовок завершена.' +
      '\nПрименено подтвержденных правил: ' +
      result.appliedCount +
      '\nКоличество перенесено без пересчета при одинаковых единицах: ' +
      result.sameUnitCount +
      '\nСохранены ручные исправления: ' +
      result.manualCount +
      '\nНе найдено правило: ' +
      result.missingRuleCount +
      '\nКонфликт правил: ' +
      result.conflictCount +
      '\nНедостаточно данных в правиле: ' +
      result.invalidRuleCount +
      (result.invalidMessages.length > 0 ? '\nПричины:\n' + result.invalidMessages.join('\n') : '') +
      '\nПропущено строк без сопоставленного товара: ' +
      result.unmatchedCount +
      '\nРассчитано цен в УС: ' +
      priceResult.calculatedCount
  );
}

function suggestPackagingRulesForSelectedDocuments() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const invoiceSheet = spreadsheet.getSheetByName(CONFIG.sourceSheetName);
  const rulesSheet = spreadsheet.getSheetByName(CONFIG.packagingRulesSheetName);

  if (!invoiceSheet) {
    throw new Error('Не найден лист: ' + CONFIG.sourceSheetName);
  }

  if (!rulesSheet) {
    throw new Error('Не найден лист: ' + CONFIG.packagingRulesSheetName);
  }

  const invoiceColumns = getColumnMap_(invoiceSheet);
  const ruleColumns = getColumnMapByHeaderRow_(rulesSheet, CONFIG.packagingRulesHeaderRow);

  requireBaseColumns_(invoiceColumns);
  requirePackagingInvoiceColumns_(invoiceColumns);
  requirePackagingRuleDraftColumns_(ruleColumns);

  const invoiceData = getActualData_(invoiceSheet, invoiceColumns);

  if (invoiceData.values.length === 0) {
    SpreadsheetApp.getUi().alert('На листе "Накладная" нет строк для черновиков правил фасовок.');
    return;
  }

  const documents = getDocumentBlocks_(invoiceData.values, invoiceColumns);
  const selectedDocuments = documents.filter((document) => {
    const firstRow = invoiceData.values[document.startIndex];
    return firstRow[invoiceColumns['Загрузка'] - 1] === true;
  });

  if (selectedDocuments.length === 0) {
    SpreadsheetApp.getUi().alert('Отметь галочкой документ, для которого нужно сформировать черновики правил фасовок.');
    return;
  }

  const activeRules = buildPackagingRules_(spreadsheet);
  const allRules = buildPackagingRuleRecordsForDrafts_(rulesSheet, ruleColumns);
  const existingRuleKeys = buildPackagingDraftKeyIndex_(allRules);
  let nextRuleNumber = getNextPackagingRuleNumber_(allRules);
  const proposals = [];
  const result = {
    createdCount: 0,
    existingRuleCount: 0,
    existingDraftCount: 0,
    sameUnitCount: 0,
    unmatchedCount: 0,
    noSuggestionCount: 0,
    conflictCount: 0,
    skippedMessages: [],
  };

  selectedDocuments.forEach((document) => {
    const documentRows = invoiceData.values.slice(document.startIndex, document.endIndex + 1);
    const firstRow = documentRows[0];

    documentRows.forEach((row, rowOffset) => {
      if (!isLoadableExportProductRow_(row, invoiceColumns) || isProductSkipRow_(row, invoiceColumns)) {
        return;
      }

      const sheetRow = CONFIG.startRow + document.startIndex + rowOffset;
      const productCode = normalizeIdentifier_(row[invoiceColumns['Код товара УС'] - 1]);
      const unitUs = normalizePackagingUnit_(row[invoiceColumns['Ед.изм. в УС'] - 1]);
      const unitDocument = normalizePackagingUnit_(row[invoiceColumns['Ед.изм. в документе'] - 1]);

      if (productCode === '' || unitUs === '') {
        result.unmatchedCount += 1;
        return;
      }

      const rowContext = buildPackagingRowContext_(row, firstRow, invoiceColumns);
      const activeMatch = findPackagingRule_(activeRules, rowContext);

      if (activeMatch.rule) {
        result.existingRuleCount += 1;
        return;
      }

      if (activeMatch.conflict) {
        result.conflictCount += 1;
        return;
      }

      const draftKey = buildPackagingDraftKeyFromContext_(rowContext, unitUs);

      if (existingRuleKeys[draftKey]) {
        result.existingDraftCount += 1;
        return;
      }

      if (unitDocument !== '' && unitDocument === unitUs) {
        result.sameUnitCount += 1;
        return;
      }

      const sourceQuantity = toCalculationNumber_(row[invoiceColumns['Кол-во в документе'] - 1]);
      const proposal = suggestPackagingRuleForInvoiceRow_(
        row,
        firstRow,
        invoiceColumns,
        sheetRow,
        sourceQuantity
      );

      if (!proposal) {
        result.noSuggestionCount += 1;
        result.skippedMessages.push(
          'строка ' +
            sheetRow +
            ': не удалось надежно предложить правило для "' +
            String(row[invoiceColumns['Наименование товара из документа'] - 1]).trim() +
            '"'
        );
        return;
      }

      nextRuleNumber += 1;
      proposal.id = 'PKG-DRAFT-' + formatPackagingRuleNumber_(nextRuleNumber);
      proposals.push(proposal);
      existingRuleKeys[draftKey] = true;
      result.createdCount += 1;
    });
  });

  if (proposals.length > 0) {
    const lastRow = rulesSheet.getLastRow();
    const nextRow = Math.max(lastRow + 1, CONFIG.packagingRulesHeaderRow + 1);
    const lastColumn = rulesSheet.getLastColumn();

    if (lastRow >= CONFIG.packagingRulesHeaderRow + 1) {
      rulesSheet
        .getRange(lastRow, 1, 1, lastColumn)
        .copyFormatToRange(rulesSheet, 1, lastColumn, nextRow, nextRow + proposals.length - 1);
    }

    const rows = proposals.map((proposal) => {
      return buildPackagingDraftRuleRow_(proposal, ruleColumns, lastColumn);
    });

    rulesSheet.getRange(nextRow, 1, rows.length, lastColumn).setValues(rows);
  }

  let message =
    'Черновики правил фасовок сформированы.' +
    '\nСоздано черновиков: ' +
    result.createdCount +
    '\nУже есть активное правило: ' +
    result.existingRuleCount +
    '\nУже есть черновик/правило: ' +
    result.existingDraftCount +
    '\nОдинаковые единицы, правило не требуется: ' +
    result.sameUnitCount +
    '\nНет кода или единицы УС: ' +
    result.unmatchedCount +
    '\nНет надежного предложения: ' +
    result.noSuggestionCount +
    '\nКонфликт активных правил: ' +
    result.conflictCount;

  if (result.skippedMessages.length > 0) {
    message += '\n\nПроверь вручную:\n' + result.skippedMessages.slice(0, 12).join('\n');

    if (result.skippedMessages.length > 12) {
      message += '\n...и еще ' + (result.skippedMessages.length - 12);
    }
  }

  SpreadsheetApp.getUi().alert(message);
}

function activateSelectedPackagingRuleDrafts() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getActiveSheet();

  if (!sheet || sheet.getName() !== CONFIG.packagingRulesSheetName) {
    SpreadsheetApp.getUi().alert('Сначала выбери строки черновиков на листе "Правила фасовок".');
    return;
  }

  const activeRange = sheet.getActiveRange();

  if (!activeRange || activeRange.getLastRow() <= CONFIG.packagingRulesHeaderRow) {
    SpreadsheetApp.getUi().alert('Выбери одну или несколько строк черновиков ниже заголовка.');
    return;
  }

  const columns = getColumnMapByHeaderRow_(sheet, CONFIG.packagingRulesHeaderRow);
  requireColumns_(columns, [
    'ID правила',
    'Активность правила',
    'Режим пересчета',
    'Ручная проверка',
    'Дата подтверждения',
    'Кем подтверждено',
  ]);

  const startRow = Math.max(activeRange.getRow(), CONFIG.packagingRulesHeaderRow + 1);
  const endRow = activeRange.getLastRow();
  let activatedCount = 0;
  let skippedCount = 0;

  for (let rowNumber = startRow; rowNumber <= endRow; rowNumber += 1) {
    const id = String(sheet.getRange(rowNumber, columns['ID правила']).getValue()).trim();
    const activity = String(sheet.getRange(rowNumber, columns['Активность правила']).getValue()).trim();
    const mode = String(sheet.getRange(rowNumber, columns['Режим пересчета']).getValue()).trim();

    if (id === '' || activity !== 'Требует проверки' || mode === '' || mode === 'Ручная проверка') {
      skippedCount += 1;
      continue;
    }

    sheet.getRange(rowNumber, columns['Активность правила']).setValue('Активно');
    sheet.getRange(rowNumber, columns['Ручная проверка']).setValue('Нет');
    sheet.getRange(rowNumber, columns['Дата подтверждения']).setValue(new Date()).setNumberFormat('dd.MM.yyyy');
    sheet.getRange(rowNumber, columns['Кем подтверждено']).setValue(getCurrentUserLabel_());
    activatedCount += 1;
  }

  SpreadsheetApp.getUi().alert(
    'Активация черновиков завершена.' +
      '\nАктивировано: ' +
      activatedCount +
      '\nПропущено: ' +
      skippedCount +
      '\n\nПосле этого нажми "Проверить выбранные документы".'
  );
}

function saveManualDryWeightsAsPackagingRules() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const invoiceSheet = spreadsheet.getSheetByName(CONFIG.sourceSheetName);
  const rulesSheet = spreadsheet.getSheetByName(CONFIG.packagingRulesSheetName);

  if (!invoiceSheet) {
    throw new Error('Не найден лист: ' + CONFIG.sourceSheetName);
  }

  if (!rulesSheet) {
    throw new Error('Не найден лист: ' + CONFIG.packagingRulesSheetName);
  }

  const invoiceColumns = getColumnMap_(invoiceSheet);
  const ruleColumns = getColumnMapByHeaderRow_(rulesSheet, CONFIG.packagingRulesHeaderRow);

  requireBaseColumns_(invoiceColumns);
  requirePackagingInvoiceColumns_(invoiceColumns);
  requireColumns_(ruleColumns, [
    'ID правила',
    'Активность правила',
    'ИНН поставщика',
    'Название из документа',
    'Код товара УС',
    'Наименование товара в УС',
    'Сухой вес единицы',
    'Режим пересчета',
    'Ручная проверка',
    'Комментарий к правилу',
    'Дата подтверждения',
    'Кем подтверждено',
  ]);

  const invoiceData = getActualData_(invoiceSheet, invoiceColumns);

  if (invoiceData.values.length === 0) {
    SpreadsheetApp.getUi().alert('На листе нет строк с ручным сухим весом.');
    return;
  }

  const documents = getDocumentBlocks_(invoiceData.values, invoiceColumns);
  const selectedDocuments = documents.filter((document) => {
    const firstRow = invoiceData.values[document.startIndex];
    return firstRow[invoiceColumns['Загрузка'] - 1] === true;
  });

  if (selectedDocuments.length === 0) {
    SpreadsheetApp.getUi().alert('Отметь галочкой документ, из которого нужно сохранить сухой вес.');
    return;
  }

  const rulesLastRow = rulesSheet.getLastRow();

  if (rulesLastRow <= CONFIG.packagingRulesHeaderRow) {
    SpreadsheetApp.getUi().alert('На листе "Правила фасовок" нет подготовленных правил.');
    return;
  }

  const ruleValues = rulesSheet
    .getRange(
      CONFIG.packagingRulesHeaderRow + 1,
      1,
      rulesLastRow - CONFIG.packagingRulesHeaderRow,
      rulesSheet.getLastColumn()
    )
    .getValues();
  const ruleRecords = ruleValues.map((row, index) => {
    return {
      sheetRow: CONFIG.packagingRulesHeaderRow + 1 + index,
      id: String(row[ruleColumns['ID правила'] - 1]).trim(),
      supplierInn: String(row[ruleColumns['ИНН поставщика'] - 1]).trim(),
      sourceName: String(row[ruleColumns['Название из документа'] - 1]).trim(),
      productCode: String(row[ruleColumns['Код товара УС'] - 1]).trim(),
      productName: String(row[ruleColumns['Наименование товара в УС'] - 1]).trim(),
      mode: String(row[ruleColumns['Режим пересчета'] - 1]).trim(),
      comment: String(row[ruleColumns['Комментарий к правилу'] - 1]).trim(),
    };
  });
  const updatesByRuleRow = {};
  const skippedMessages = [];

  selectedDocuments.forEach((document) => {
    const documentRows = invoiceData.values.slice(document.startIndex, document.endIndex + 1);
    const firstRow = documentRows[0];

    documentRows.forEach((row, rowOffset) => {
      if (!isLoadableExportProductRow_(row, invoiceColumns) || isProductSkipRow_(row, invoiceColumns)) {
        return;
      }

      if (!isManualQuantity_(row[invoiceColumns['Количество исправлено вручную'] - 1])) {
        return;
      }

      const sheetRow = CONFIG.startRow + document.startIndex + rowOffset;
      const productCode = String(row[invoiceColumns['Код товара УС'] - 1]).trim();
      const productName = String(row[invoiceColumns['Наименование товара в УС'] - 1]).trim();
      const originalName = String(row[invoiceColumns['Наименование товара из документа'] - 1]).trim();
      const supplierInn = String(getDocumentValue_(row, firstRow, invoiceColumns, 'ИНН Поставщика')).trim();
      const documentQuantity = toCalculationNumber_(row[invoiceColumns['Кол-во в документе'] - 1]);
      const totalDryWeight = toCalculationNumber_(row[invoiceColumns['Кол-во в УС'] - 1]);

      if (productCode === '' || documentQuantity === null || documentQuantity <= 0 || totalDryWeight === null || totalDryWeight < 0) {
        skippedMessages.push('строка ' + sheetRow + ': недостаточно данных для расчета сухого веса одной упаковки');
        return;
      }

      let matchingRules = ruleRecords.filter((rule) => {
        return rule.productCode === productCode && rule.mode === 'По сухому весу';
      });
      const contextualRules = matchingRules.filter((rule) => {
        const innMatches = rule.supplierInn === '' || normalizeIdentifier_(rule.supplierInn) === normalizeIdentifier_(supplierInn);
        const nameMatches =
          rule.sourceName === '' || normalizeProductName_(rule.sourceName) === normalizeProductName_(originalName);
        return innMatches && nameMatches;
      });

      if (contextualRules.length > 0) {
        matchingRules = contextualRules;
      }

      if (matchingRules.length !== 1) {
        skippedMessages.push('строка ' + sheetRow + ': не найдено одно подходящее правило по сухому весу');
        return;
      }

      const rule = matchingRules[0];
      const dryWeightPerUnit = Math.round((totalDryWeight / documentQuantity) * 1000000) / 1000000;

      if (updatesByRuleRow[rule.sheetRow] && Math.abs(updatesByRuleRow[rule.sheetRow].dryWeightPerUnit - dryWeightPerUnit) > 0.000001) {
        skippedMessages.push('правило ' + rule.id + ': в документе указаны разные значения сухого веса');
        delete updatesByRuleRow[rule.sheetRow];
        return;
      }

      updatesByRuleRow[rule.sheetRow] = {
        rule: rule,
        invoiceSheetRow: sheetRow,
        productName: productName || rule.productName,
        documentQuantity: documentQuantity,
        totalDryWeight: totalDryWeight,
        dryWeightPerUnit: dryWeightPerUnit,
      };
    });
  });

  const updates = Object.keys(updatesByRuleRow).map((key) => updatesByRuleRow[key]);

  if (updates.length === 0) {
    let message = 'Нет ручных значений, которые можно сохранить как правило.';

    if (skippedMessages.length > 0) {
      message += '\n\n' + skippedMessages.join('\n');
    }

    SpreadsheetApp.getUi().alert(message);
    return;
  }

  const summary = updates.map((item) => {
    return (
      item.productName +
      ': ' +
      item.totalDryWeight.toFixed(3).replace('.', ',') +
      ' кг / ' +
      item.documentQuantity.toString().replace('.', ',') +
      ' = ' +
      item.dryWeightPerUnit.toFixed(3).replace('.', ',') +
      ' кг на единицу'
    );
  });
  const confirmation = SpreadsheetApp.getUi().alert(
    'Сохранить сухой вес как постоянное правило?',
    summary.join('\n') + '\n\nПосле подтверждения правило станет активным для следующих документов.',
    SpreadsheetApp.getUi().ButtonSet.YES_NO
  );

  if (confirmation !== SpreadsheetApp.getUi().Button.YES) {
    SpreadsheetApp.getUi().alert('Сохранение правил отменено. Ручные значения в накладной не изменены.');
    return;
  }

  updates.forEach((item) => {
    const confirmationText =
      'Сухой вес ' + item.dryWeightPerUnit.toFixed(3).replace('.', ',') + ' кг сохранен из ручной правки накладной.';
    const comment = item.rule.comment === '' ? confirmationText : item.rule.comment + '\n' + confirmationText;

    rulesSheet.getRange(item.rule.sheetRow, ruleColumns['Сухой вес единицы']).setValue(item.dryWeightPerUnit).setNumberFormat('0.000');
    rulesSheet.getRange(item.rule.sheetRow, ruleColumns['Активность правила']).setValue('Активно');
    rulesSheet.getRange(item.rule.sheetRow, ruleColumns['Ручная проверка']).setValue('Нет');
    rulesSheet.getRange(item.rule.sheetRow, ruleColumns['Комментарий к правилу']).setValue(comment);
    rulesSheet.getRange(item.rule.sheetRow, ruleColumns['Дата подтверждения']).setValue(new Date()).setNumberFormat('dd.MM.yyyy');
    rulesSheet.getRange(item.rule.sheetRow, ruleColumns['Кем подтверждено']).setValue('Калькулятор');

    if (invoiceColumns['ID правила фасовки']) {
      invoiceSheet.getRange(item.invoiceSheetRow, invoiceColumns['ID правила фасовки']).setValue(item.rule.id);
    }

    invoiceSheet
      .getRange(item.invoiceSheetRow, invoiceColumns['Количество исправлено вручную'])
      .clearContent();
  });

  let message = 'Сохранено и активировано правил по сухому весу: ' + updates.length;

  if (skippedMessages.length > 0) {
    message += '\n\nПропущено:\n' + skippedMessages.join('\n');
  }

  SpreadsheetApp.getUi().alert(message);
}

function checkSelectedDocuments() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(CONFIG.sourceSheetName);
  const columns = getColumnMap_(sheet);
  requireBaseColumns_(columns);

  const data = getActualData_(sheet, columns);

  if (data.values.length === 0) {
    SpreadsheetApp.getUi().alert('На листе нет строк для проверки.');
    return;
  }

  const documents = getDocumentBlocks_(data.values, columns);
  const selectedDocuments = documents.filter((document) => {
    const firstRow = data.values[document.startIndex];
    return firstRow[columns['Загрузка'] - 1] === true;
  });

  if (selectedDocuments.length === 0) {
    SpreadsheetApp.getUi().alert('Отметь галочкой документ, который нужно проверить.');
    return;
  }

  let checkedRowsCount = 0;
  const context = buildProductMatchingContext_(spreadsheet);

  selectedDocuments.forEach((document) => {
    applyProductMatching_(sheet, data.values, columns, document, context);
  });

  const matchingData = getActualData_(sheet, columns);
  const packagingResult = applyPackagingRulesForDocuments_(
    spreadsheet,
    sheet,
    matchingData.values,
    columns,
    selectedDocuments
  );
  const packagingData = getActualData_(sheet, columns);
  const priceResult = calculateUsPricesForDocuments_(sheet, packagingData.values, columns, selectedDocuments);

  const refreshedData = getActualData_(sheet, columns);

  selectedDocuments.forEach((document) => {
    checkedRowsCount += applyDocumentCheck_(sheet, refreshedData.values, columns, document);
  });

  SpreadsheetApp.getUi().alert(
    'Проверка выбранных документов завершена. Документов: ' +
      selectedDocuments.length +
      ', строк: ' +
      checkedRowsCount +
      ', применено правил фасовок: ' +
      packagingResult.appliedCount +
      ', требуют правила фасовок: ' +
      (packagingResult.missingRuleCount + packagingResult.conflictCount + packagingResult.invalidRuleCount) +
      ', рассчитано цен в УС: ' +
      priceResult.calculatedCount
  );
}

function checkReadinessByStatus() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(CONFIG.sourceSheetName);
  const columns = getColumnMap_(sheet);
  requireBaseColumns_(columns);

  const data = getActualData_(sheet, columns);

  if (data.values.length === 0) {
    SpreadsheetApp.getUi().alert('На листе нет строк для проверки.');
    return;
  }

  const documents = getDocumentBlocks_(data.values, columns);
  const context = buildProductMatchingContext_(spreadsheet);

  documents.forEach((document) => {
    applyProductMatching_(sheet, data.values, columns, document, context);
  });

  const matchingData = getActualData_(sheet, columns);
  const packagingResult = applyPackagingRulesForDocuments_(
    spreadsheet,
    sheet,
    matchingData.values,
    columns,
    documents
  );
  const packagingData = getActualData_(sheet, columns);
  const priceResult = calculateUsPricesForDocuments_(sheet, packagingData.values, columns, documents);

  const refreshedData = getActualData_(sheet, columns);

  documents.forEach((document) => {
    applyDocumentCheck_(sheet, refreshedData.values, columns, document);
  });

  SpreadsheetApp.getUi().alert(
      'Обновление всех статусов завершено. Обработано строк: ' +
      data.values.length +
      ', применено правил фасовок: ' +
      packagingResult.appliedCount +
      ', требуют правила фасовок: ' +
      (packagingResult.missingRuleCount + packagingResult.conflictCount + packagingResult.invalidRuleCount) +
      ', рассчитано цен в УС: ' +
      priceResult.calculatedCount
  );
}

function loadSelectedDocumentsToTestSheet() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sourceSheet = spreadsheet.getSheetByName(CONFIG.sourceSheetName);
  const targetSheet = spreadsheet.getSheetByName(CONFIG.targetSheetName);
  const columns = getColumnMap_(sourceSheet);

  requireBaseColumns_(columns);

  const exportHeaders = [
    'Дата документа',
    '№ Документа',
    'Поставщик',
    'ИНН Поставщика',
    'Получатель',
    'Торговая точка',
    'Склад',
    'Основание',
    'Наименование товара в УС',
    'Код товара УС',
    'Ставка НДС',
    'Сумма НДС',
    'Общая стоимость',
    'Сумма накладной',
    'Ед.изм. в УС',
    'Кол-во в УС',
    'Цена в УС',
  ];

  requireColumns_(columns, exportHeaders);

  let data = getActualData_(sourceSheet, columns);

  if (data.values.length === 0) {
    SpreadsheetApp.getUi().alert('На листе нет строк для загрузки.');
    return;
  }

  const documents = getDocumentBlocks_(data.values, columns);
  const selectedDocuments = documents.filter((document) => {
    const firstRow = data.values[document.startIndex];
    return firstRow[columns['Загрузка'] - 1] === true;
  });

  if (selectedDocuments.length === 0) {
    SpreadsheetApp.getUi().alert('Отметь галочкой хотя бы один документ в колонке "Загрузка".');
    return;
  }

  calculateUsPricesForDocuments_(sourceSheet, data.values, columns, selectedDocuments);
  data = getActualData_(sourceSheet, columns);

  const rowsToCopy = [];
  const skippedDocuments = [];
  const partiallyLoadedMessages = [];
  let skippedProductRowsCount = 0;

  selectedDocuments.forEach((document) => {
    const documentRows = data.values.slice(document.startIndex, document.endIndex + 1);
    const firstRow = documentRows[0];
    const documentNumber = firstRow[columns['№ Документа'] - 1] || 'без номера';
    const documentLoadStatus = String(firstRow[columns['Статус загрузки'] - 1]).trim();

    if (documentLoadStatus !== LOAD_STATUS.READY) {
      skippedDocuments.push(documentNumber);
      clearDocumentCheckboxes_(sourceSheet, columns, document);
      return;
    }

    let skippedInDocument = 0;

    documentRows.forEach((row) => {
      if (!isLoadableExportProductRow_(row, columns)) {
        return;
      }

      if (isProductSkipRow_(row, columns)) {
        skippedInDocument += 1;
        skippedProductRowsCount += 1;
        return;
      }

      const exportRow = exportHeaders.map((header) => {
        return getExportValue_(row, firstRow, columns, header);
      });

      rowsToCopy.push(exportRow);
    });

    if (skippedInDocument > 0) {
      partiallyLoadedMessages.push(documentNumber + ': пропущено строк "Не загружать" - ' + skippedInDocument);
    }

    markDocumentAsLoaded_(sourceSheet, columns, document);
  });

  if (rowsToCopy.length === 0) {
    SpreadsheetApp.getUi().alert(
      'Нет документов, готовых к загрузке целиком. Проверь строки со статусом "Не готово" или "Требует проверки".'
    );
    return;
  }

  ensureTargetHeaders_(targetSheet, exportHeaders);

  const targetStartRow = targetSheet.getLastRow() + 1;

  targetSheet
    .getRange(targetStartRow, 1, rowsToCopy.length, exportHeaders.length)
    .setValues(rowsToCopy);

  formatTargetSheet_(targetSheet, targetStartRow, rowsToCopy.length, exportHeaders);

  let message = 'Тестовая загрузка завершена. Скопировано строк: ' + rowsToCopy.length;

  if (skippedProductRowsCount > 0) {
    message +=
      '\n\nДокументы загружены частично. Строки со статусом "Не загружать" не копировались: ' +
      skippedProductRowsCount +
      '.';
  }

  if (partiallyLoadedMessages.length > 0) {
    message += '\n\nДетализация:\n' + partiallyLoadedMessages.join('\n');
  }

  if (skippedDocuments.length > 0) {
    message += '\n\nНе загружены документы, где есть неготовые строки:\n' + skippedDocuments.join(', ');
  }

  SpreadsheetApp.getUi().alert(message);
}

function returnSelectedDocumentsToReview() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(CONFIG.sourceSheetName);
  const columns = getColumnMap_(sheet);
  requireBaseColumns_(columns);

  const data = getActualData_(sheet, columns);

  if (data.values.length === 0) {
    SpreadsheetApp.getUi().alert('На листе нет строк для возврата на проверку.');
    return;
  }

  const documents = getDocumentBlocks_(data.values, columns);
  const selectedDocuments = documents.filter((document) => {
    const firstRow = data.values[document.startIndex];
    return firstRow[columns['Загрузка'] - 1] === true;
  });

  if (selectedDocuments.length === 0) {
    SpreadsheetApp.getUi().alert('Отметь галочкой документ, который нужно вернуть на проверку.');
    return;
  }

  let returnedCount = 0;
  const skippedDocuments = [];

  selectedDocuments.forEach((document) => {
    const documentRows = data.values.slice(document.startIndex, document.endIndex + 1);
    const firstRow = documentRows[0];
    const documentNumber = firstRow[columns['№ Документа'] - 1] || 'без номера';

    const isLoadedDocument = documentRows.some((row) => {
      const loadStatus = String(row[columns['Статус загрузки'] - 1]).trim();
      const rowStatus = String(row[columns['Статус строки'] - 1]).trim();

      return loadStatus === LOAD_STATUS.LOADED || rowStatus === ROW_STATUS.SENT;
    });

    if (!isLoadedDocument) {
      skippedDocuments.push(documentNumber);
      return;
    }

    const rowCount = document.endIndex - document.startIndex + 1;
    const firstSheetRow = CONFIG.startRow + document.startIndex;

    const checkboxValues = Array.from({ length: rowCount }, () => [false]);

    sheet.getRange(firstSheetRow, columns['Статус загрузки']).setValue(LOAD_STATUS.REVIEW);
    sheet.getRange(firstSheetRow, columns['Статус загрузки']).setBackground(COLORS.review);
    sheet.getRange(firstSheetRow, columns['Статус строки']).setValue(ROW_STATUS.RETURN);
    sheet.getRange(firstSheetRow, columns['Статус строки']).setBackground(COLORS.returnReview);
    sheet.getRange(firstSheetRow, columns['Загрузка'], rowCount, 1).setValues(checkboxValues);

    if (rowCount > 1) {
      sheet.getRange(firstSheetRow + 1, columns['Статус загрузки'], rowCount - 1, 1).clearContent().setBackground(COLORS.empty);
      sheet.getRange(firstSheetRow + 1, columns['Статус строки'], rowCount - 1, 1).clearContent().setBackground(COLORS.empty);
    }

    returnedCount += 1;
  });

  let message = 'Возвращено на проверку документов: ' + returnedCount;

  if (skippedDocuments.length > 0) {
    message += '\n\nПропущены документы, которые еще не были загружены:\n' + skippedDocuments.join(', ');
  }

  SpreadsheetApp.getUi().alert(message);
}

function applyDocumentCheck_(sheet, values, columns, document) {
  const documentRows = values.slice(document.startIndex, document.endIndex + 1);
  const firstRow = documentRows[0];
  const firstRowStatus = String(firstRow[columns['Статус строки'] - 1]).trim();
  const productReadiness = getProductReadiness_(documentRows, columns);

  const hasDuplicateYes = documentRows.some((row) => {
    return String(row[columns['Дубль'] - 1]).trim() === 'Да';
  });

  const hasDuplicateQuestion = documentRows.some((row) => {
    return String(row[columns['Дубль'] - 1]).trim() === '?';
  });

  const hasOcrError = documentRows.some((row) => {
    if (isProductSkipRow_(row, columns)) {
      return false;
    }

    return String(row[columns['Корректировка'] - 1]).trim() === 'Ошибка OCR';
  });

  const hasManualCorrection = documentRows.some((row) => {
    if (isProductSkipRow_(row, columns)) {
      return false;
    }

    const correction = String(row[columns['Корректировка'] - 1]).trim();
    if (!MANUAL_CORRECTIONS.includes(correction)) {
      return false;
    }

    return !isResolvedProductCorrection_(row, columns, correction);
  });

  const isLoaded = firstRowStatus === ROW_STATUS.SENT;
  const isReturned = firstRowStatus === ROW_STATUS.RETURN;

  let loadStatus = LOAD_STATUS.CHECK;
  let loadColor = COLORS.check;
  let rowStatus = firstRowStatus || ROW_STATUS.RECOGNIZED;
  let rowStatusColor = getRowStatusColor_(rowStatus);
  let shouldClearCorrections = false;

  if (isLoaded) {
    loadStatus = LOAD_STATUS.LOADED;
    loadColor = COLORS.loaded;
    rowStatus = ROW_STATUS.SENT;
    rowStatusColor = COLORS.loaded;
  } else if (hasDuplicateYes || hasOcrError) {
    loadStatus = LOAD_STATUS.NOT_READY;
    loadColor = COLORS.notReady;
    rowStatus = hasOcrError ? ROW_STATUS.ERROR : ROW_STATUS.RECOGNIZED;
    rowStatusColor = hasOcrError ? COLORS.notReady : COLORS.check;
  } else if (hasDuplicateQuestion) {
    loadStatus = LOAD_STATUS.REVIEW;
    loadColor = COLORS.review;
    rowStatus = ROW_STATUS.RECOGNIZED;
    rowStatusColor = COLORS.check;
  } else if (hasManualCorrection) {
    loadStatus = LOAD_STATUS.REVIEW;
    loadColor = COLORS.review;
    rowStatus = ROW_STATUS.MANUAL;
    rowStatusColor = COLORS.review;
  } else if (productReadiness.hasWaitCreate || productReadiness.hasNoLoadableRows) {
    loadStatus = LOAD_STATUS.NOT_READY;
    loadColor = COLORS.notReady;
    rowStatus = ROW_STATUS.MANUAL;
    rowStatusColor = COLORS.notReady;
  } else if (productReadiness.hasProductProblem) {
    loadStatus = LOAD_STATUS.REVIEW;
    loadColor = COLORS.review;
    rowStatus = ROW_STATUS.MANUAL;
    rowStatusColor = COLORS.review;
  } else if (isReturned) {
    loadStatus = LOAD_STATUS.REVIEW;
    loadColor = COLORS.review;
    rowStatus = ROW_STATUS.RETURN;
    rowStatusColor = COLORS.returnReview;
  } else {
    loadStatus = LOAD_STATUS.READY;
    loadColor = COLORS.ready;
    rowStatus = ROW_STATUS.READY;
    rowStatusColor = COLORS.ready;
    shouldClearCorrections = true;
  }

  const rowCount = document.endIndex - document.startIndex + 1;
  const firstSheetRow = CONFIG.startRow + document.startIndex;

  sheet.getRange(firstSheetRow, columns['Статус загрузки']).setValue(loadStatus);
  sheet.getRange(firstSheetRow, columns['Статус загрузки']).setBackground(loadColor);
  sheet.getRange(firstSheetRow, columns['Статус строки']).setValue(rowStatus);
  sheet.getRange(firstSheetRow, columns['Статус строки']).setBackground(rowStatusColor);

  if (rowCount > 1) {
    sheet.getRange(firstSheetRow + 1, columns['Статус загрузки'], rowCount - 1, 1).clearContent().setBackground(COLORS.empty);
    sheet.getRange(firstSheetRow + 1, columns['Статус строки'], rowCount - 1, 1).clearContent().setBackground(COLORS.empty);
  }

  if (shouldClearCorrections) {
    sheet.getRange(firstSheetRow, columns['Корректировка'], rowCount, 1).clearContent().setBackground(COLORS.empty);
  }

  return countLoadableProductRows_(documentRows, columns);
}

function buildProductMatchingContext_(spreadsheet) {
  const productSheet = spreadsheet.getSheetByName(CONFIG.productSheetName);
  const aliasSheet = spreadsheet.getSheetByName(CONFIG.aliasSheetName);
  const newProductsSheet = spreadsheet.getSheetByName(CONFIG.newProductsSheetName);

  if (!productSheet) {
    throw new Error('Не найден лист: ' + CONFIG.productSheetName);
  }

  if (!aliasSheet) {
    throw new Error('Не найден лист: ' + CONFIG.aliasSheetName);
  }

  if (!newProductsSheet) {
    throw new Error('Не найден лист: ' + CONFIG.newProductsSheetName);
  }

  const productColumns = getProductDirectoryColumnMap_(productSheet);
  const aliasColumns = getColumnMapByHeaderRow_(aliasSheet, CONFIG.aliasHeaderRow);
  const newProductColumns = getColumnMapByHeaderRow_(newProductsSheet, CONFIG.newProductsHeaderRow);

  requireColumns_(productColumns, ['Наименование', 'Код в УС', 'Ед. изм.']);
  requireColumns_(aliasColumns, [
    'ID сопоставления',
    'Поставщик',
    'ИНН поставщика',
    'Название из документа',
    'Нормализованное название',
    'Ед. изм. из документа',
    'Наименование товара в УС',
    'Код товара УС',
    'Ед. изм. в УС',
    'Тип сопоставления',
    'Статус сопоставления',
    'Дата подтверждения',
    'Кем подтверждено',
  ]);
  requireColumns_(newProductColumns, [
    'ID нового товара',
    'ID документа',
    'ID строки',
    'Поставщик',
    'ИНН поставщика',
    'Название из документа',
    'Нормализованное название',
    'Ед. изм. из документа',
    'Предлагаемое название УС',
    'Ед. изм. в УС',
    'Решение пользователя',
    'Статус нового товара',
    'Наименование товара в УС',
    'Код товара УС',
    'Дата создания записи',
  ]);

  return {
    productSheet: productSheet,
    aliasSheet: aliasSheet,
    newProductsSheet: newProductsSheet,
    productColumns: productColumns,
    aliasColumns: aliasColumns,
    newProductColumns: newProductColumns,
    productList: buildProductList_(productSheet, productColumns),
    productIndex: buildProductIndex_(productSheet, productColumns),
    productCodeIndex: buildProductCodeIndex_(productSheet, productColumns),
    aliasIndex: buildAliasIndex_(aliasSheet, aliasColumns),
    newProductKeys: buildNewProductKeys_(newProductsSheet, newProductColumns),
  };
}

function refreshNewProductChoices_(spreadsheet) {
  const productSheet = spreadsheet.getSheetByName(CONFIG.productSheetName);
  const newProductsSheet = spreadsheet.getSheetByName(CONFIG.newProductsSheetName);

  if (!productSheet) {
    throw new Error('Не найден лист: ' + CONFIG.productSheetName);
  }

  if (!newProductsSheet) {
    throw new Error('Не найден лист: ' + CONFIG.newProductsSheetName);
  }

  const productColumns = getProductDirectoryColumnMap_(productSheet);
  const newProductColumns = getColumnMapByHeaderRow_(newProductsSheet, CONFIG.newProductsHeaderRow);

  requireColumns_(productColumns, ['Наименование', 'Код в УС', 'Ед. изм.']);
  requireColumns_(newProductColumns, [
    'Название из документа',
    'Нормализованное название',
    'Ед. изм. из документа',
    'Предлагаемое название УС',
    'Решение пользователя',
    'Статус нового товара',
    'Наименование товара в УС',
    'Код товара УС',
  ]);

  const lastRow = newProductsSheet.getLastRow();

  if (lastRow <= CONFIG.newProductsHeaderRow) {
    return { rowsWithChoices: 0, rowsWithoutChoices: 0 };
  }

  const products = buildProductList_(productSheet, productColumns);
  const values = newProductsSheet
    .getRange(CONFIG.newProductsHeaderRow + 1, 1, lastRow - CONFIG.newProductsHeaderRow, newProductsSheet.getLastColumn())
    .getValues();
  let rowsWithChoices = 0;
  let rowsWithoutChoices = 0;

  values.forEach((row, index) => {
    const sheetRow = CONFIG.newProductsHeaderRow + 1 + index;
    const status = String(row[newProductColumns['Статус нового товара'] - 1]).trim();
    const productCode = String(row[newProductColumns['Код товара УС'] - 1]).trim();
    const targetCell = newProductsSheet.getRange(sheetRow, newProductColumns['Наименование товара в УС']);

    if (status === 'Сопоставлен' || status === 'Ожидает создания в УС' || productCode !== '') {
      targetCell.clearDataValidations();
      return;
    }

    const queries = [
      row[newProductColumns['Предлагаемое название УС'] - 1],
      row[newProductColumns['Наименование товара в УС'] - 1],
      row[newProductColumns['Нормализованное название'] - 1],
      row[newProductColumns['Название из документа'] - 1],
    ];
    const documentUnit = String(row[newProductColumns['Ед. изм. из документа'] - 1]).trim();
    const suggestedProducts = getProductSuggestions_(
      products,
      queries,
      documentUnit,
      CONFIG.productSuggestionLimit
    );

    if (suggestedProducts.length === 0) {
      targetCell.clearDataValidations();
      rowsWithoutChoices += 1;
      return;
    }

    const dropdownValues = suggestedProducts.map((product) => buildProductSelectionLabel_(product));
    const validation = SpreadsheetApp.newDataValidation()
      .requireValueInList(dropdownValues, true)
      .setAllowInvalid(true)
      .setHelpText('Выберите подходящий товар УС. Код и единица измерения заполнятся автоматически.')
      .build();

    targetCell.setDataValidation(validation);
    rowsWithChoices += 1;
  });

  SpreadsheetApp.flush();

  return {
    rowsWithChoices: rowsWithChoices,
    rowsWithoutChoices: rowsWithoutChoices,
  };
}

function applySelectedProductFromDropdown_(event) {
  const sheet = event.range.getSheet();
  const columns = getColumnMapByHeaderRow_(sheet, CONFIG.newProductsHeaderRow);

  requireColumns_(columns, [
    'Решение пользователя',
    'Статус нового товара',
    'Наименование товара в УС',
    'Код товара УС',
    'Ед. изм. в УС',
  ]);

  if (event.range.getColumn() !== columns['Наименование товара в УС']) {
    return;
  }

  const selectedValue = String(event.value || '').trim();

  if (selectedValue === '') {
    return;
  }

  const spreadsheet = event.source || SpreadsheetApp.getActiveSpreadsheet();
  const productSheet = spreadsheet.getSheetByName(CONFIG.productSheetName);

  if (!productSheet) {
    throw new Error('Не найден лист: ' + CONFIG.productSheetName);
  }

  const productColumns = getProductDirectoryColumnMap_(productSheet);
  requireColumns_(productColumns, ['Наименование', 'Код в УС', 'Ед. изм.']);

  const products = buildProductList_(productSheet, productColumns);
  const selectedProduct = resolveProductSelection_(products, selectedValue, '');

  if (!selectedProduct) {
    return;
  }

  const sheetRow = event.range.getRow();
  event.range.setValue(selectedProduct.name);
  event.range.clearDataValidations();
  sheet.getRange(sheetRow, columns['Код товара УС']).setValue(selectedProduct.code);
  sheet.getRange(sheetRow, columns['Ед. изм. в УС']).setValue(selectedProduct.unit);
  sheet.getRange(sheetRow, columns['Решение пользователя']).setValue('Сопоставить');
  sheet.getRange(sheetRow, columns['Статус нового товара']).setValue('Ожидает выбора');
}

function applyProductMatching_(sheet, values, columns, document, context) {
  const documentRows = values.slice(document.startIndex, document.endIndex + 1);
  const firstRow = documentRows[0];
  const documentId = String(firstRow[columns['ID документа'] - 1]).trim();
  const supplier = String(firstRow[columns['Поставщик'] - 1]).trim();
  const supplierInn = String(firstRow[columns['ИНН Поставщика'] - 1]).trim();

  let matchedCount = 0;
  let unresolvedCount = 0;
  let newQueueCount = 0;

  documentRows.forEach((row, rowOffset) => {
    const sheetRow = CONFIG.startRow + document.startIndex + rowOffset;
    const productMatchStatus = getProductMatchStatus_(row, columns);

    if (
      productMatchStatus === PRODUCT_MATCH_STATUS.SKIP ||
      productMatchStatus === PRODUCT_MATCH_STATUS.WAIT_CREATE
    ) {
      return;
    }

    const originalName = String(row[columns['Наименование товара из документа'] - 1]).trim();
    const suggestedProductName = String(row[columns['Наименование товара в УС'] - 1]).trim();
    const productCode = String(row[columns['Код товара УС'] - 1]).trim();
    const documentUnit = String(row[columns['Ед.изм. в документе'] - 1]).trim();
    const lineId = String(row[columns['ID строки'] - 1]).trim();

    if (originalName === '' && suggestedProductName === '') {
      return;
    }

    if (productCode !== '' && suggestedProductName !== '') {
      if (productMatchStatus === '') {
        sheet.getRange(sheetRow, columns['Статус сопоставления товара']).setValue(PRODUCT_MATCH_STATUS.FOUND);
      }

      clearProductCorrection_(sheet, columns, sheetRow);

      matchedCount += 1;
      return;
    }

    const normalizedOriginalName = normalizeProductName_(originalName);
    const alias = findAlias_(context.aliasIndex, supplierInn, supplier, originalName, normalizedOriginalName);

    if (alias) {
      writeProductMatchToInvoice_(sheet, columns, sheetRow, alias.productName, alias.productCode, alias.unit, PRODUCT_MATCH_STATUS.FOUND);
      clearProductCorrection_(sheet, columns, sheetRow);
      matchedCount += 1;
      return;
    }

    // Предварительное название от OCR/AI используется только как подсказка.
    // Автоматически связываем со справочником лишь при точном совпадении исходного названия.
    const exactProduct = findProductByName_(context.productIndex, originalName);

    if (exactProduct) {
      writeProductMatchToInvoice_(
        sheet,
        columns,
        sheetRow,
        exactProduct.name,
        exactProduct.code,
        exactProduct.unit,
        PRODUCT_MATCH_STATUS.FOUND
      );

      appendAliasIfNeeded_(
        context,
        supplier,
        supplierInn,
        originalName,
        normalizedOriginalName,
        documentUnit,
        exactProduct.name,
        exactProduct.code,
        exactProduct.unit,
        'Автоматически'
      );

      clearProductCorrection_(sheet, columns, sheetRow);

      matchedCount += 1;
      return;
    }

    const unresolvedStatus = suggestedProductName !== '' ? PRODUCT_MATCH_STATUS.NEED_CHOICE : PRODUCT_MATCH_STATUS.NEW;
    const correction = suggestedProductName !== '' ? 'Сопоставление' : 'Нет в справочнике';

    sheet.getRange(sheetRow, columns['Статус сопоставления товара']).setValue(unresolvedStatus);
    sheet.getRange(sheetRow, columns['Корректировка']).setValue(correction);

    if (addNewProductQueueRowIfNeeded_(
      context,
      documentId,
      lineId,
      supplier,
      supplierInn,
      originalName,
      normalizedOriginalName,
      documentUnit,
      suggestedProductName,
      unresolvedStatus
    )) {
      newQueueCount += 1;
    }

    unresolvedCount += 1;
  });

  return {
    matchedCount: matchedCount,
    unresolvedCount: unresolvedCount,
    newQueueCount: newQueueCount,
  };
}

function buildProductList_(sheet, columns) {
  const lastRow = sheet.getLastRow();
  const products = [];

  if (lastRow < 2) {
    return products;
  }

  const values = sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).getValues();

  values.forEach((row) => {
    const name = String(row[columns['Наименование'] - 1]).trim();
    const code = String(row[columns['Код в УС'] - 1]).trim();
    const unit = String(row[columns['Ед. изм.'] - 1]).trim();
    const active = columns['Активен'] ? String(row[columns['Активен'] - 1]).trim().toLowerCase() : 'да';

    if (name === '' || code === '') {
      return;
    }

    if (active !== '' && active !== 'да') {
      return;
    }

    products.push({
      name: name,
      code: code,
      unit: unit,
    });
  });

  return products;
}

function getProductSuggestions_(products, queryValues, documentUnit, limit) {
  const queries = uniqueValues_(queryValues.map((value) => String(value || '').trim())).filter((value) => value !== '');
  const scoredProducts = [];

  products.forEach((product) => {
    let bestScore = -1;

    queries.forEach((query) => {
      const score = scoreProductSuggestion_(product, query, documentUnit);

      if (score > bestScore) {
        bestScore = score;
      }
    });

    if (bestScore >= 120) {
      scoredProducts.push({
        product: product,
        score: bestScore,
      });
    }
  });

  scoredProducts.sort((left, right) => {
    if (right.score !== left.score) {
      return right.score - left.score;
    }

    return left.product.name.localeCompare(right.product.name, 'ru');
  });

  const result = [];
  const usedCodes = {};

  scoredProducts.forEach((item) => {
    if (result.length >= limit || usedCodes[item.product.code]) {
      return;
    }

    usedCodes[item.product.code] = true;
    result.push(item.product);
  });

  return result;
}

function scoreProductSuggestion_(product, query, documentUnit) {
  const normalizedQuery = normalizeProductSearchText_(query);
  const normalizedProductName = normalizeProductSearchText_(product.name);
  const queryTokens = getSignificantProductTokens_(normalizedQuery);
  const productTokens = getSignificantProductTokens_(normalizedProductName);

  if (normalizedQuery === '' || normalizedProductName === '' || queryTokens.length === 0 || productTokens.length === 0) {
    return -1;
  }

  let score = 0;
  let matchedTokens = 0;

  queryTokens.forEach((queryToken) => {
    let bestSimilarity = 0;

    productTokens.forEach((productToken) => {
      const similarity = getProductTokenSimilarity_(queryToken, productToken);

      if (similarity > bestSimilarity) {
        bestSimilarity = similarity;
      }
    });

    if (bestSimilarity >= 0.6) {
      matchedTokens += 1;
      score += bestSimilarity * 100;
    }
  });

  if (matchedTokens === 0) {
    return -1;
  }

  score += (matchedTokens / queryTokens.length) * 100;

  if (normalizedQuery === normalizedProductName) {
    score += 1000;
  } else if (normalizedQuery.indexOf(normalizedProductName) !== -1 || normalizedProductName.indexOf(normalizedQuery) !== -1) {
    score += 200;
  }

  if (documentUnit !== '' && normalizeUnit_(documentUnit) === normalizeUnit_(product.unit)) {
    score += 20;
  }

  return score;
}

function normalizeProductSearchText_(value) {
  return String(value)
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/(\d)[,.](\d)/g, '$1_$2')
    .replace(/[^0-9a-zа-я%_]+/gi, ' ')
    .replace(/_/g, '.')
    .replace(/\s+/g, ' ')
    .trim();
}

function getSignificantProductTokens_(normalizedValue) {
  const stopWords = {
    в: true,
    и: true,
    из: true,
    к: true,
    на: true,
    от: true,
    по: true,
    с: true,
    со: true,
    для: true,
    без: true,
    уп: true,
    упак: true,
    упаковка: true,
    упаковке: true,
    пачка: true,
    короб: true,
    коробка: true,
    банка: true,
    бутылка: true,
    шт: true,
    кг: true,
    г: true,
    гр: true,
    л: true,
    мл: true,
    литр: true,
    литра: true,
    килограмм: true,
    килограмма: true,
  };

  return normalizedValue.split(' ').filter((token) => {
    if (token === '' || stopWords[token]) {
      return false;
    }

    if (/^\d+(?:\.\d+)?(?:кг|г|гр|л|мл|шт)$/.test(token)) {
      return false;
    }

    return token.length >= 2;
  });
}

function getProductTokenSimilarity_(leftToken, rightToken) {
  if (leftToken === rightToken) {
    return 1;
  }

  const shortestLength = Math.min(leftToken.length, rightToken.length);

  if (shortestLength >= 5 && (leftToken.indexOf(rightToken) === 0 || rightToken.indexOf(leftToken) === 0)) {
    return 0.75;
  }

  if (shortestLength >= 5 && getLevenshteinDistance_(leftToken, rightToken) <= 1) {
    return 0.65;
  }

  return 0;
}

function getLevenshteinDistance_(leftValue, rightValue) {
  const left = String(leftValue);
  const right = String(rightValue);
  const previousRow = [];

  for (let rightIndex = 0; rightIndex <= right.length; rightIndex += 1) {
    previousRow[rightIndex] = rightIndex;
  }

  for (let leftIndex = 1; leftIndex <= left.length; leftIndex += 1) {
    const currentRow = [leftIndex];

    for (let rightIndex = 1; rightIndex <= right.length; rightIndex += 1) {
      const substitutionCost = left[leftIndex - 1] === right[rightIndex - 1] ? 0 : 1;
      currentRow[rightIndex] = Math.min(
        currentRow[rightIndex - 1] + 1,
        previousRow[rightIndex] + 1,
        previousRow[rightIndex - 1] + substitutionCost
      );
    }

    for (let rightIndex = 0; rightIndex <= right.length; rightIndex += 1) {
      previousRow[rightIndex] = currentRow[rightIndex];
    }
  }

  return previousRow[right.length];
}

function buildProductSelectionLabel_(product) {
  const parts = [product.name, product.code];

  if (product.unit !== '') {
    parts.push(product.unit);
  }

  return parts.join(' | ');
}

function resolveProductSelection_(products, selectedValue, selectedUnit) {
  const value = String(selectedValue || '').trim();

  if (value === '') {
    return null;
  }

  const labelMatches = products.filter((product) => buildProductSelectionLabel_(product) === value);

  if (labelMatches.length === 1) {
    return labelMatches[0];
  }

  const nameMatches = products.filter((product) => {
    if (normalizeProductName_(product.name) !== normalizeProductName_(value)) {
      return false;
    }

    return selectedUnit === '' || normalizeUnit_(product.unit) === normalizeUnit_(selectedUnit);
  });

  return nameMatches.length === 1 ? nameMatches[0] : null;
}

function buildProductIndex_(sheet, columns) {
  const lastRow = sheet.getLastRow();
  const index = {};

  if (lastRow < 2) {
    return index;
  }

  const values = sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).getValues();

  values.forEach((row) => {
    const name = String(row[columns['Наименование'] - 1]).trim();
    const code = String(row[columns['Код в УС'] - 1]).trim();
    const unit = String(row[columns['Ед. изм.'] - 1]).trim();
    const active = columns['Активен'] ? String(row[columns['Активен'] - 1]).trim().toLowerCase() : 'да';

    if (name === '' || code === '') {
      return;
    }

    if (active !== '' && active !== 'да') {
      return;
    }

    const key = normalizeProductName_(name);

    if (!index[key]) {
      index[key] = [];
    }

    index[key].push({
      name: name,
      code: code,
      unit: unit,
    });
  });

  return index;
}

function buildProductCodeIndex_(sheet, columns) {
  const lastRow = sheet.getLastRow();
  const index = {};

  if (lastRow < 2) {
    return index;
  }

  const values = sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn()).getValues();

  values.forEach((row) => {
    const name = String(row[columns['Наименование'] - 1]).trim();
    const code = String(row[columns['Код в УС'] - 1]).trim();
    const unit = String(row[columns['Ед. изм.'] - 1]).trim();

    if (code === '') {
      return;
    }

    index[code] = {
      name: name,
      code: code,
      unit: unit,
    };
  });

  return index;
}

function buildInvoiceRowIndex_(sheet, columns) {
  const lastRow = sheet.getLastRow();
  const index = {};
  let currentDocumentId = '';

  if (lastRow < CONFIG.startRow) {
    return index;
  }

  const values = sheet
    .getRange(CONFIG.startRow, 1, lastRow - CONFIG.startRow + 1, sheet.getLastColumn())
    .getValues();

  values.forEach((row, rowIndex) => {
    const rowDocumentId = String(row[columns['ID документа'] - 1]).trim();
    const lineId = String(row[columns['ID строки'] - 1]).trim();
    const originalName = columns['Наименование товара из документа']
      ? String(row[columns['Наименование товара из документа'] - 1]).trim()
      : '';
    const productMatchStatus = columns['Статус сопоставления товара']
      ? String(row[columns['Статус сопоставления товара'] - 1]).trim()
      : '';
    const hasDocumentStart =
      row[columns['Дата документа'] - 1] !== '' ||
      row[columns['№ Документа'] - 1] !== '' ||
      row[columns['Поставщик'] - 1] !== '' ||
      rowDocumentId !== '';

    if (hasDocumentStart && rowDocumentId !== '') {
      currentDocumentId = rowDocumentId;
    }

    if (lineId !== '') {
      const record = {
        rowNumber: CONFIG.startRow + rowIndex,
        productMatchStatus: productMatchStatus,
      };
      const keys = [
        currentDocumentId + '|' + lineId + '|' + normalizeProductName_(originalName),
        currentDocumentId + '|' + lineId,
        '|' + lineId,
      ];

      uniqueValues_(keys).forEach((key) => {
        if (!index[key]) {
          index[key] = [];
        }

        index[key].push(record);
      });
    }
  });

  return index;
}

function findInvoiceRowNumber_(index, documentId, lineId, originalName) {
  const keys = [
    String(documentId).trim() + '|' + String(lineId).trim() + '|' + normalizeProductName_(originalName),
    String(documentId).trim() + '|' + String(lineId).trim(),
    '|' + String(lineId).trim(),
  ];

  for (let keyIndex = 0; keyIndex < keys.length; keyIndex += 1) {
    const records = index[keys[keyIndex]] || [];

    if (records.length === 0) {
      continue;
    }

    const unresolvedRecord = records.find((record) => {
      return (
        record.productMatchStatus === PRODUCT_MATCH_STATUS.NEED_CHOICE ||
        record.productMatchStatus === PRODUCT_MATCH_STATUS.NEW
      );
    });

    if (unresolvedRecord) {
      return unresolvedRecord.rowNumber;
    }

    const waitingRecord = records.find((record) => {
      return record.productMatchStatus === PRODUCT_MATCH_STATUS.WAIT_CREATE;
    });

    return (waitingRecord || records[0]).rowNumber;
  }

  return null;
}

function buildAliasIndex_(sheet, columns) {
  const lastRow = sheet.getLastRow();
  const index = {};

  if (lastRow <= CONFIG.aliasHeaderRow) {
    return index;
  }

  const values = sheet
    .getRange(CONFIG.aliasHeaderRow + 1, 1, lastRow - CONFIG.aliasHeaderRow, sheet.getLastColumn())
    .getValues();

  values.forEach((row) => {
    const supplier = String(row[columns['Поставщик'] - 1]).trim();
    const supplierInn = String(row[columns['ИНН поставщика'] - 1]).trim();
    const originalName = String(row[columns['Название из документа'] - 1]).trim();
    const normalizedName = String(row[columns['Нормализованное название'] - 1]).trim();
    const productName = String(row[columns['Наименование товара в УС'] - 1]).trim();
    const productCode = String(row[columns['Код товара УС'] - 1]).trim();
    const unit = String(row[columns['Ед. изм. в УС'] - 1]).trim();
    const status = String(row[columns['Статус сопоставления'] - 1]).trim();

    if (productName === '' || productCode === '') {
      return;
    }

    if (status !== '' && status !== 'Активно') {
      return;
    }

    const alias = {
      productName: productName,
      productCode: productCode,
      unit: unit,
    };

    addAliasIndexKey_(index, supplierInn, originalName, alias);
    addAliasIndexKey_(index, supplier, originalName, alias);
    addAliasIndexKey_(index, supplierInn, normalizedName, alias);
    addAliasIndexKey_(index, supplier, normalizedName, alias);
  });

  return index;
}

function addAliasIndexKey_(index, supplierKey, productKey, alias) {
  const normalizedSupplierKey = normalizeProductName_(supplierKey);
  const normalizedProductKey = normalizeProductName_(productKey);

  if (normalizedSupplierKey === '' || normalizedProductKey === '') {
    return;
  }

  index[normalizedSupplierKey + '|' + normalizedProductKey] = alias;
}

function findAlias_(aliasIndex, supplierInn, supplier, originalName, normalizedOriginalName) {
  const keys = [
    normalizeProductName_(supplierInn) + '|' + normalizeProductName_(originalName),
    normalizeProductName_(supplier) + '|' + normalizeProductName_(originalName),
    normalizeProductName_(supplierInn) + '|' + normalizeProductName_(normalizedOriginalName),
    normalizeProductName_(supplier) + '|' + normalizeProductName_(normalizedOriginalName),
  ];

  for (let index = 0; index < keys.length; index += 1) {
    const key = keys[index];

    if (aliasIndex[key]) {
      return aliasIndex[key];
    }
  }

  return null;
}

function findProductByName_(productIndex, name) {
  const key = normalizeProductName_(name);
  const products = productIndex[key] || [];

  if (products.length === 1) {
    return products[0];
  }

  return null;
}

function findProductByNameAndUnit_(productIndex, name, unit) {
  const key = normalizeProductName_(name);
  const products = productIndex[key] || [];

  if (products.length === 0) {
    return null;
  }

  if (unit === '') {
    return products.length === 1 ? products[0] : null;
  }

  const sameUnitProducts = products.filter((product) => {
    return normalizeUnit_(product.unit) === normalizeUnit_(unit);
  });

  return sameUnitProducts.length === 1 ? sameUnitProducts[0] : null;
}

function writeProductMatchToInvoice_(sheet, columns, sheetRow, productName, productCode, unit, status) {
  sheet.getRange(sheetRow, columns['Наименование товара в УС']).setValue(productName);
  sheet.getRange(sheetRow, columns['Код товара УС']).setValue(productCode);

  if (unit !== '') {
    sheet.getRange(sheetRow, columns['Ед.изм. в УС']).setValue(unit);
  }

  sheet.getRange(sheetRow, columns['Статус сопоставления товара']).setValue(status);
}

function clearProductCorrection_(sheet, columns, sheetRow) {
  sheet.getRange(sheetRow, columns['Корректировка']).clearContent().setBackground(COLORS.empty);
}

function appendAliasIfNeeded_(
  context,
  supplier,
  supplierInn,
  originalName,
  normalizedOriginalName,
  documentUnit,
  productName,
  productCode,
  productUnit,
  matchType
) {
  const existingAlias = findAlias_(context.aliasIndex, supplierInn, supplier, originalName, normalizedOriginalName);

  if (existingAlias) {
    return false;
  }

  const sheet = context.aliasSheet;
  const columns = context.aliasColumns;
  const nextRow = Math.max(sheet.getLastRow() + 1, CONFIG.aliasHeaderRow + 1);
  const row = Array.from({ length: sheet.getLastColumn() }, () => '');
  const aliasId = 'ALIAS-' + Utilities.getUuid().slice(0, 8);

  row[columns['ID сопоставления'] - 1] = aliasId;
  row[columns['Поставщик'] - 1] = supplier;
  row[columns['ИНН поставщика'] - 1] = supplierInn;
  row[columns['Название из документа'] - 1] = originalName;
  row[columns['Нормализованное название'] - 1] = normalizedOriginalName;
  row[columns['Ед. изм. из документа'] - 1] = documentUnit;
  row[columns['Наименование товара в УС'] - 1] = productName;
  row[columns['Код товара УС'] - 1] = productCode;
  row[columns['Ед. изм. в УС'] - 1] = productUnit;
  // В текущей таблице на колонке "Тип сопоставления" может стоять строгий список
  // для статуса. Поэтому тип пока не записываем, чтобы не ломать применение решений.
  row[columns['Тип сопоставления'] - 1] = '';
  row[columns['Статус сопоставления'] - 1] = 'Активно';
  row[columns['Дата подтверждения'] - 1] = new Date();
  row[columns['Кем подтверждено'] - 1] = 'Система';

  sheet.getRange(nextRow, 1, 1, row.length).setValues([row]);
  addAliasIndexKey_(context.aliasIndex, supplierInn, originalName, {
    productName: productName,
    productCode: productCode,
    unit: productUnit,
  });

  return true;
}

function markAliasesForReview_(context, supplier, supplierInn, originalName, normalizedName) {
  const sheet = context.aliasSheet;
  const columns = context.aliasColumns;
  const lastRow = sheet.getLastRow();

  if (lastRow <= CONFIG.aliasHeaderRow) {
    return 0;
  }

  const values = sheet
    .getRange(CONFIG.aliasHeaderRow + 1, 1, lastRow - CONFIG.aliasHeaderRow, sheet.getLastColumn())
    .getValues();
  const normalizedSupplier = normalizeProductName_(supplier);
  const normalizedSupplierInn = normalizeProductName_(supplierInn);
  const normalizedOriginalName = normalizeProductName_(originalName);
  const normalizedSearchName = normalizeProductName_(normalizedName);
  let markedCount = 0;

  values.forEach((row, index) => {
    const rowSupplier = normalizeProductName_(row[columns['Поставщик'] - 1]);
    const rowSupplierInn = normalizeProductName_(row[columns['ИНН поставщика'] - 1]);
    const rowOriginalName = normalizeProductName_(row[columns['Название из документа'] - 1]);
    const rowNormalizedName = normalizeProductName_(row[columns['Нормализованное название'] - 1]);
    const supplierMatches =
      (normalizedSupplierInn !== '' && rowSupplierInn === normalizedSupplierInn) ||
      (normalizedSupplier !== '' && rowSupplier === normalizedSupplier);
    const productMatches =
      rowOriginalName === normalizedOriginalName ||
      (normalizedSearchName !== '' && rowNormalizedName === normalizedSearchName);

    if (!supplierMatches || !productMatches) {
      return;
    }

    const sheetRow = CONFIG.aliasHeaderRow + 1 + index;
    const statusCell = sheet.getRange(sheetRow, columns['Статус сопоставления']);
    setValueKeepingValidation_(statusCell, 'Требует проверки');
    markedCount += 1;
  });

  return markedCount;
}

function reopenNewProductQueueRow_(context, documentId, lineId, originalName, suggestedProductName) {
  const sheet = context.newProductsSheet;
  const columns = context.newProductColumns;
  const lastRow = sheet.getLastRow();

  if (lastRow <= CONFIG.newProductsHeaderRow) {
    return false;
  }

  const values = sheet
    .getRange(CONFIG.newProductsHeaderRow + 1, 1, lastRow - CONFIG.newProductsHeaderRow, sheet.getLastColumn())
    .getValues();

  for (let index = 0; index < values.length; index += 1) {
    const row = values[index];
    const rowDocumentId = String(row[columns['ID документа'] - 1]).trim();
    const rowLineId = String(row[columns['ID строки'] - 1]).trim();
    const rowOriginalName = String(row[columns['Название из документа'] - 1]).trim();

    if (
      rowDocumentId !== String(documentId).trim() ||
      rowLineId !== String(lineId).trim() ||
      normalizeProductName_(rowOriginalName) !== normalizeProductName_(originalName)
    ) {
      continue;
    }

    const sheetRow = CONFIG.newProductsHeaderRow + 1 + index;
    setValueKeepingValidation_(sheet.getRange(sheetRow, columns['Решение пользователя']), 'Сопоставить');
    setValueKeepingValidation_(sheet.getRange(sheetRow, columns['Статус нового товара']), 'Ожидает выбора');
    sheet.getRange(sheetRow, columns['Наименование товара в УС']).setValue(suggestedProductName);
    sheet.getRange(sheetRow, columns['Код товара УС']).clearContent();
    return true;
  }

  return false;
}

function setValueKeepingValidation_(cell, value) {
  const validation = cell.getDataValidation();

  try {
    cell.setValue(value);
  } catch (error) {
    cell.clearDataValidations();
    cell.setValue(value);

    if (validation) {
      cell.setDataValidation(validation);
    }
  }
}

function buildNewProductKeys_(sheet, columns) {
  const lastRow = sheet.getLastRow();
  const keys = {};

  if (lastRow <= CONFIG.newProductsHeaderRow) {
    return keys;
  }

  const values = sheet
    .getRange(CONFIG.newProductsHeaderRow + 1, 1, lastRow - CONFIG.newProductsHeaderRow, sheet.getLastColumn())
    .getValues();

  values.forEach((row) => {
    const documentId = String(row[columns['ID документа'] - 1]).trim();
    const lineId = String(row[columns['ID строки'] - 1]).trim();
    const originalName = String(row[columns['Название из документа'] - 1]).trim();

    if (documentId !== '' || lineId !== '') {
      keys[documentId + '|' + lineId + '|' + normalizeProductName_(originalName)] = true;
    }
  });

  return keys;
}

function addNewProductQueueRowIfNeeded_(
  context,
  documentId,
  lineId,
  supplier,
  supplierInn,
  originalName,
  normalizedOriginalName,
  documentUnit,
  suggestedProductName,
  productMatchStatus
) {
  const key = documentId + '|' + lineId + '|' + normalizeProductName_(originalName);

  if (context.newProductKeys[key]) {
    return false;
  }

  const sheet = context.newProductsSheet;
  const columns = context.newProductColumns;
  const nextRow = Math.max(sheet.getLastRow() + 1, CONFIG.newProductsHeaderRow + 1);
  const row = Array.from({ length: sheet.getLastColumn() }, () => '');
  const newProductId = 'NEW-' + Utilities.getUuid().slice(0, 8);

  row[columns['ID нового товара'] - 1] = newProductId;
  row[columns['ID документа'] - 1] = documentId;
  row[columns['ID строки'] - 1] = lineId;
  row[columns['Поставщик'] - 1] = supplier;
  row[columns['ИНН поставщика'] - 1] = supplierInn;
  row[columns['Название из документа'] - 1] = originalName;
  row[columns['Нормализованное название'] - 1] = normalizedOriginalName;
  row[columns['Ед. изм. из документа'] - 1] = documentUnit;
  row[columns['Предлагаемое название УС'] - 1] = suggestedProductName || normalizedOriginalName;
  row[columns['Решение пользователя'] - 1] = productMatchStatus === PRODUCT_MATCH_STATUS.NEED_CHOICE ? 'Сопоставить' : '';
  row[columns['Статус нового товара'] - 1] =
    productMatchStatus === PRODUCT_MATCH_STATUS.NEED_CHOICE ? 'Ожидает выбора' : 'Новый';
  row[columns['Наименование товара в УС'] - 1] = suggestedProductName;
  row[columns['Дата создания записи'] - 1] = new Date();

  sheet.getRange(nextRow, 1, 1, row.length).setValues([row]);
  context.newProductKeys[key] = true;

  return true;
}

function normalizeProductName_(value) {
  return String(value)
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/[.,;:!?()[\]{}"«»]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function normalizeUnit_(value) {
  const unit = String(value).toLowerCase().replace(/\./g, '').trim();

  if (unit === 'килограмм' || unit === 'килограммы') return 'кг';
  if (unit === 'литр' || unit === 'литры') return 'л';
  if (unit === 'штука' || unit === 'штуки') return 'шт';

  return unit;
}

function requirePackagingRuleDraftColumns_(columns) {
  requireColumns_(columns, [
    'ID правила',
    'Активность правила',
    'Приоритет правила',
    'Поставщик',
    'ИНН поставщика',
    'Код товара поставщика',
    'Название из документа',
    'Код товара УС',
    'Наименование товара в УС',
    'Склад / назначение',
    'Ед. изм. документа',
    'Тип упаковки',
    'Количество вложений',
    'Ед. изм. вложения',
    'Вес / объем единицы',
    'Ед. изм. веса/объема',
    'Сухой вес единицы',
    'Ед. изм. в УС',
    'Режим пересчета',
    'Коэффициент',
    'Округление',
    'Ручная проверка',
    'Комментарий к правилу',
    'Дата подтверждения',
    'Кем подтверждено',
  ]);
}

function buildPackagingRuleRecordsForDrafts_(sheet, columns) {
  const startRow = CONFIG.packagingRulesHeaderRow + 1;
  const lastRow = sheet.getLastRow();

  if (lastRow < startRow) {
    return [];
  }

  const values = sheet
    .getRange(startRow, 1, lastRow - startRow + 1, sheet.getLastColumn())
    .getValues();

  return values
    .map((row, index) => {
      return {
        sheetRow: startRow + index,
        id: String(row[columns['ID правила'] - 1]).trim(),
        activity: String(row[columns['Активность правила'] - 1]).trim(),
        supplier: normalizeProductSearchText_(row[columns['Поставщик'] - 1]),
        supplierInn: normalizeIdentifier_(row[columns['ИНН поставщика'] - 1]),
        supplierProductCode: normalizeIdentifier_(row[columns['Код товара поставщика'] - 1]),
        originalName: normalizeProductName_(row[columns['Название из документа'] - 1]),
        productCode: normalizeIdentifier_(row[columns['Код товара УС'] - 1]),
        destination: normalizeProductSearchText_(row[columns['Склад / назначение'] - 1]),
        unitDocument: normalizePackagingUnit_(row[columns['Ед. изм. документа'] - 1]),
        unitUs: normalizePackagingUnit_(row[columns['Ед. изм. в УС'] - 1]),
      };
    })
    .filter((rule) => rule.id !== '' || rule.productCode !== '');
}

function buildPackagingDraftKeyIndex_(rules) {
  const index = {};

  rules.forEach((rule) => {
    const key = buildPackagingDraftKeyFromRecord_(rule);

    if (key !== '') {
      index[key] = true;
    }
  });

  return index;
}

function buildPackagingDraftKeyFromRecord_(rule) {
  if (rule.productCode === '') return '';

  return [
    rule.productCode,
    rule.supplierInn || rule.supplier,
    rule.supplierProductCode,
    rule.originalName,
    rule.destination,
    rule.unitDocument,
    rule.unitUs,
  ].join('|');
}

function buildPackagingDraftKeyFromContext_(context, unitUs) {
  if (context.productCode === '') return '';

  return [
    context.productCode,
    context.supplierInn || context.supplier,
    context.supplierProductCode,
    context.originalName,
    context.destination,
    context.unitDocument,
    normalizePackagingUnit_(unitUs),
  ].join('|');
}

function getNextPackagingRuleNumber_(rules) {
  let maxNumber = 0;

  rules.forEach((rule) => {
    const match = String(rule.id).match(/(\d+)$/);

    if (!match) {
      return;
    }

    const number = Number(match[1]);

    if (isFinite(number) && number > maxNumber) {
      maxNumber = number;
    }
  });

  return maxNumber;
}

function formatPackagingRuleNumber_(number) {
  if (number < 10) return '00' + number;
  if (number < 100) return '0' + number;
  return String(number);
}

function suggestPackagingRuleForInvoiceRow_(row, firstRow, columns, sheetRow, sourceQuantity) {
  const originalName = String(row[columns['Наименование товара из документа'] - 1]).trim();
  const productName = String(row[columns['Наименование товара в УС'] - 1]).trim();
  const productCode = String(row[columns['Код товара УС'] - 1]).trim();
  const unitDocument = normalizePackagingUnit_(row[columns['Ед.изм. в документе'] - 1]);
  const unitUs = normalizePackagingUnit_(row[columns['Ед.изм. в УС'] - 1]);
  const facts = extractPackagingFactsFromName_(originalName);
  const baseProposal = buildBasePackagingDraftProposal_(row, firstRow, columns, {
    originalName: originalName,
    productName: productName,
    productCode: productCode,
    unitDocument: unitDocument,
    unitUs: unitUs,
    packageType: guessPackagingType_(originalName, unitDocument, unitUs),
  });

  if (requiresDryWeightReview_(originalName, unitUs)) {
    return null;
  }

  if (isWeightPackagingUnit_(unitUs)) {
    const weightFact = pickFirstPackagingFact_(facts.weights);

    if (!weightFact) {
      return null;
    }

    const convertedWeight = convertPackagingAmount_(weightFact.value, weightFact.unit, unitUs);

    if (convertedWeight === null || convertedWeight <= 0) {
      return null;
    }

    const roundedWeight = roundPackagingDraftNumber_(convertedWeight);
    const resultQuantity = sourceQuantity === null ? null : roundPackagingDraftNumber_(sourceQuantity * roundedWeight);

    baseProposal.mode = 'По весу';
    baseProposal.unitWeightOrVolume = roundedWeight;
    baseProposal.parameterUnit = unitUs;
    baseProposal.rounding = '3 знака';
    baseProposal.comment = buildPackagingDraftComment_(
      sheetRow,
      sourceQuantity,
      unitDocument,
      roundedWeight,
      unitUs,
      resultQuantity,
      unitUs,
      'Сформировано автоматически из веса в названии товара.'
    );
    return baseProposal;
  }

  if (isVolumePackagingUnit_(unitUs)) {
    const volumeFact = pickFirstPackagingFact_(facts.volumes);
    let convertedVolume = null;
    let sourceNote = 'Сформировано автоматически из объема в названии товара.';

    if (volumeFact) {
      convertedVolume = convertPackagingAmount_(volumeFact.value, volumeFact.unit, unitUs);
    } else {
      const weightFact = pickFirstPackagingFact_(facts.weights);

      if (weightFact && looksLikeLiquidProduct_(originalName)) {
        convertedVolume = convertWeightToLiquidVolumeDraft_(weightFact.value, weightFact.unit, unitUs);
        sourceNote =
          'Черновик с допущением для жидкости: масса из названия приравнена к объему. Перед активацией проверь.';
      }
    }

    if (convertedVolume === null || convertedVolume <= 0) {
      return null;
    }

    const roundedVolume = roundPackagingDraftNumber_(convertedVolume);
    const resultQuantity = sourceQuantity === null ? null : roundPackagingDraftNumber_(sourceQuantity * roundedVolume);

    baseProposal.mode = 'По объему';
    baseProposal.unitWeightOrVolume = roundedVolume;
    baseProposal.parameterUnit = unitUs;
    baseProposal.rounding = '3 знака';
    baseProposal.comment = buildPackagingDraftComment_(
      sheetRow,
      sourceQuantity,
      unitDocument,
      roundedVolume,
      unitUs,
      resultQuantity,
      unitUs,
      sourceNote
    );
    return baseProposal;
  }

  const nestedFact = pickPackagingCountFactForUnit_(facts.counts, unitUs);

  if (nestedFact && nestedFact.value > 1) {
    const resultQuantity = sourceQuantity === null ? null : roundPackagingDraftNumber_(sourceQuantity * nestedFact.value);

    baseProposal.mode = 'По количеству вложений';
    baseProposal.nestedQuantity = nestedFact.value;
    baseProposal.nestedUnit = unitUs;
    baseProposal.rounding = 'До целого';
    baseProposal.comment = buildPackagingDraftComment_(
      sheetRow,
      sourceQuantity,
      unitDocument,
      nestedFact.value,
      unitUs,
      resultQuantity,
      unitUs,
      'Сформировано автоматически из количества вложений в названии товара.'
    );
    return baseProposal;
  }

  if (isPackageAccountingUnit_(unitUs)) {
    const characteristic = pickFirstPackagingFact_(facts.weights) || pickFirstPackagingFact_(facts.volumes);

    baseProposal.mode = 'Без пересчета';
    baseProposal.rounding = 'До целого';

    if (characteristic) {
      baseProposal.unitWeightOrVolume = characteristic.value;
      baseProposal.parameterUnit = characteristic.unit;
    }

    baseProposal.comment =
      'Строка ' +
      sheetRow +
      ': количество документа переносится без пересчета в "' +
      unitUs +
      '".' +
      (characteristic
        ? ' Параметр ' +
          formatPackagingDraftNumber_(characteristic.value) +
          ' ' +
          characteristic.unit +
          ' сохранен как характеристика товара.'
        : '') +
      ' Перед активацией проверь, что товар действительно учитывается упаковками/штуками.';
    return baseProposal;
  }

  return null;
}

function buildBasePackagingDraftProposal_(row, firstRow, columns, options) {
  return {
    id: '',
    activity: 'Требует проверки',
    priority: 1,
    supplier: String(getDocumentValue_(row, firstRow, columns, 'Поставщик')).trim(),
    supplierInn: String(getDocumentValue_(row, firstRow, columns, 'ИНН Поставщика')).trim(),
    supplierProductCode: columns['Код товара поставщика']
      ? String(row[columns['Код товара поставщика'] - 1]).trim()
      : '',
    originalName: options.originalName,
    productCode: options.productCode,
    productName: options.productName,
    destination: String(getDocumentValue_(row, firstRow, columns, 'Склад')).trim(),
    unitDocument: options.unitDocument,
    packageType: options.packageType,
    nestedQuantity: '',
    nestedUnit: '',
    unitWeightOrVolume: '',
    parameterUnit: '',
    dryWeight: '',
    unitUs: options.unitUs,
    mode: '',
    coefficient: '',
    rounding: '',
    manualReview: 'Нет',
    comment: '',
    confirmationDate: '',
    confirmedBy: '',
  };
}

function buildPackagingDraftRuleRow_(proposal, columns, columnCount) {
  const row = Array.from({ length: columnCount }, () => '');

  setPackagingDraftCell_(row, columns, 'ID правила', proposal.id);
  setPackagingDraftCell_(row, columns, 'Активность правила', proposal.activity);
  setPackagingDraftCell_(row, columns, 'Приоритет правила', proposal.priority);
  setPackagingDraftCell_(row, columns, 'Поставщик', proposal.supplier);
  setPackagingDraftCell_(row, columns, 'ИНН поставщика', proposal.supplierInn);
  setPackagingDraftCell_(row, columns, 'Код товара поставщика', proposal.supplierProductCode);
  setPackagingDraftCell_(row, columns, 'Название из документа', proposal.originalName);
  setPackagingDraftCell_(row, columns, 'Код товара УС', proposal.productCode);
  setPackagingDraftCell_(row, columns, 'Наименование товара в УС', proposal.productName);
  setPackagingDraftCell_(row, columns, 'Склад / назначение', proposal.destination);
  setPackagingDraftCell_(row, columns, 'Ед. изм. документа', proposal.unitDocument);
  setPackagingDraftCell_(row, columns, 'Тип упаковки', proposal.packageType);
  setPackagingDraftCell_(row, columns, 'Количество вложений', proposal.nestedQuantity);
  setPackagingDraftCell_(row, columns, 'Ед. изм. вложения', proposal.nestedUnit);
  setPackagingDraftCell_(row, columns, 'Вес / объем единицы', proposal.unitWeightOrVolume);
  setPackagingDraftCell_(row, columns, 'Ед. изм. веса/объема', proposal.parameterUnit);
  setPackagingDraftCell_(row, columns, 'Сухой вес единицы', proposal.dryWeight);
  setPackagingDraftCell_(row, columns, 'Ед. изм. в УС', proposal.unitUs);
  setPackagingDraftCell_(row, columns, 'Режим пересчета', proposal.mode);
  setPackagingDraftCell_(row, columns, 'Коэффициент', proposal.coefficient);
  setPackagingDraftCell_(row, columns, 'Округление', proposal.rounding);
  setPackagingDraftCell_(row, columns, 'Ручная проверка', proposal.manualReview);
  setPackagingDraftCell_(row, columns, 'Комментарий к правилу', proposal.comment);
  setPackagingDraftCell_(row, columns, 'Дата подтверждения', proposal.confirmationDate);
  setPackagingDraftCell_(row, columns, 'Кем подтверждено', proposal.confirmedBy);

  return row;
}

function setPackagingDraftCell_(row, columns, header, value) {
  if (!columns[header]) return;
  row[columns[header] - 1] = value;
}

function extractPackagingFactsFromName_(name) {
  const text = String(name).toUpperCase().replace(/,/g, '.');
  const regex =
    /(\d+(?:\.\d+)?)\s*(КГ|КИЛОГРАММ(?:А|ОВ|Ы)?|МЛ|МИЛЛИЛИТР(?:А|ОВ|Ы)?|Л|ЛИТР(?:А|ОВ|Ы)?|ГРАММ(?:А|ОВ|Ы)?|ГР?|ШТ|ШТУК(?:А|И)?|РУЛ|РУЛОН(?:А|ОВ|Ы)?|БУТ|БУТЫЛК(?:А|И)?|ПАЧ|ПАЧК(?:А|И)?|УПАК|УПАКОВК(?:А|И)?|БАН|БАНК(?:А|И)?)/g;
  const facts = {
    weights: [],
    volumes: [],
    counts: [],
  };
  let match = regex.exec(text);

  while (match) {
    const value = Number(match[1]);
    const unit = normalizePackagingUnit_(match[2]);

    if (isFinite(value) && value > 0) {
      const fact = {
        value: value,
        unit: unit,
      };

      if (isWeightPackagingUnit_(unit)) {
        facts.weights.push(fact);
      } else if (isVolumePackagingUnit_(unit)) {
        facts.volumes.push(fact);
      } else {
        facts.counts.push(fact);
      }
    }

    match = regex.exec(text);
  }

  return facts;
}

function pickFirstPackagingFact_(facts) {
  return facts && facts.length > 0 ? facts[0] : null;
}

function pickPackagingCountFactForUnit_(facts, unit) {
  const normalizedUnit = normalizePackagingUnit_(unit);

  for (let index = 0; index < facts.length; index += 1) {
    if (facts[index].unit === normalizedUnit) {
      return facts[index];
    }
  }

  return null;
}

function isWeightPackagingUnit_(unit) {
  const normalizedUnit = normalizePackagingUnit_(unit);
  return normalizedUnit === 'кг' || normalizedUnit === 'г';
}

function isVolumePackagingUnit_(unit) {
  const normalizedUnit = normalizePackagingUnit_(unit);
  return normalizedUnit === 'л' || normalizedUnit === 'мл';
}

function isPackageAccountingUnit_(unit) {
  return ['шт', 'пач', 'упак', 'бут', 'бан', 'рул'].includes(normalizePackagingUnit_(unit));
}

function requiresDryWeightReview_(name, unitUs) {
  if (!isWeightPackagingUnit_(unitUs)) return false;

  const text = normalizeProductSearchText_(name);
  return (
    text.indexOf('оливки') !== -1 ||
    text.indexOf('маслины') !== -1 ||
    text.indexOf('рассол') !== -1 ||
    text.indexOf('заливк') !== -1 ||
    text.indexOf('маринад') !== -1
  );
}

function looksLikeLiquidProduct_(name) {
  const text = normalizeProductSearchText_(name);
  return (
    text.indexOf('молоко') !== -1 ||
    text.indexOf('сливки') !== -1 ||
    text.indexOf('кефир') !== -1 ||
    text.indexOf('ряженка') !== -1 ||
    text.indexOf('йогурт') !== -1 ||
    text.indexOf('сироп') !== -1 ||
    text.indexOf('сок') !== -1 ||
    text.indexOf('напит') !== -1 ||
    text.indexOf('вода') !== -1
  );
}

function convertWeightToLiquidVolumeDraft_(value, sourceUnit, targetUnit) {
  const grams = convertPackagingAmount_(value, sourceUnit, 'г');

  if (grams === null) {
    return null;
  }

  if (targetUnit === 'л') return grams / 1000;
  if (targetUnit === 'мл') return grams;
  return null;
}

function guessPackagingType_(name, unitDocument, unitUs) {
  const text = normalizeProductSearchText_(name);

  if (text.indexOf('канистр') !== -1) return 'канистра';
  if (text.indexOf('бут') !== -1 || text.indexOf('пэт') !== -1) return 'бутылка';
  if (text.indexOf('бан') !== -1) return 'банка';
  if (text.indexOf('рул') !== -1) return 'рулон';
  if (text.indexOf('пач') !== -1 || text.indexOf('пак') !== -1) return 'пачка';
  if (unitUs === 'бут') return 'бутылка';
  if (unitUs === 'бан') return 'банка';
  if (unitUs === 'рул') return 'рулон';
  if (unitUs === 'пач' || unitUs === 'упак') return 'пачка';
  if (unitDocument === 'шт') return 'пачка';
  return unitDocument || unitUs;
}

function buildPackagingDraftComment_(
  sheetRow,
  sourceQuantity,
  sourceUnit,
  factor,
  factorUnit,
  resultQuantity,
  resultUnit,
  note
) {
  let calculationText;

  if (sourceQuantity === null || resultQuantity === null) {
    calculationText =
      'Количество документа × ' +
      formatPackagingDraftNumber_(factor) +
      ' ' +
      factorUnit +
      ' = количество в ' +
      resultUnit +
      '.';
  } else {
    calculationText =
      formatPackagingDraftNumber_(sourceQuantity) +
      ' ' +
      sourceUnit +
      ' × ' +
      formatPackagingDraftNumber_(factor) +
      ' ' +
      factorUnit +
      ' = ' +
      formatPackagingDraftNumber_(resultQuantity) +
      ' ' +
      resultUnit +
      '.';
  }

  return 'Строка ' + sheetRow + ': ' + calculationText + ' ' + note;
}

function roundPackagingDraftNumber_(value) {
  return Math.round(value * 1000000) / 1000000;
}

function formatPackagingDraftNumber_(value) {
  const rounded = roundPackagingDraftNumber_(value);
  return String(rounded).replace('.', ',');
}

function getCurrentUserLabel_() {
  try {
    const email = Session.getActiveUser().getEmail();

    if (email) {
      return email;
    }
  } catch (error) {
    // Some Apps Script contexts do not expose the active user.
  }

  return 'Пользователь';
}

function applyPackagingRulesForDocuments_(spreadsheet, sheet, values, columns, documents) {
  requirePackagingInvoiceColumns_(columns);

  const rules = buildPackagingRules_(spreadsheet);
  const result = {
    appliedCount: 0,
    sameUnitCount: 0,
    manualCount: 0,
    missingRuleCount: 0,
    conflictCount: 0,
    invalidRuleCount: 0,
    invalidMessages: [],
    unmatchedCount: 0,
  };

  documents.forEach((document) => {
    const documentRows = values.slice(document.startIndex, document.endIndex + 1);
    const firstRow = documentRows[0];

    documentRows.forEach((row, rowOffset) => {
      if (!isLoadableExportProductRow_(row, columns) || isProductSkipRow_(row, columns)) {
        return;
      }

      const sheetRow = CONFIG.startRow + document.startIndex + rowOffset;
      const productCode = String(row[columns['Код товара УС'] - 1]).trim();
      const unitDocument = normalizePackagingUnit_(row[columns['Ед.изм. в документе'] - 1]);
      const unitUs = normalizePackagingUnit_(row[columns['Ед.изм. в УС'] - 1]);
      const sourceQuantity = toCalculationNumber_(row[columns['Кол-во в документе'] - 1]);
      const manualQuantity = isManualQuantity_(row[columns['Количество исправлено вручную'] - 1]);

      if (productCode === '' || unitUs === '') {
        result.unmatchedCount += 1;
        return;
      }

      if (manualQuantity) {
        const currentQuantity = toCalculationNumber_(row[columns['Кол-во в УС'] - 1]);

        if (currentQuantity !== null && currentQuantity >= 0) {
          clearPackagingCorrection_(sheet, columns, sheetRow);
          result.manualCount += 1;
        } else {
          markPackagingReview_(sheet, columns, sheetRow, false);
          result.invalidRuleCount += 1;
        }

        return;
      }

      if (sourceQuantity === null || sourceQuantity < 0 || unitDocument === '') {
        markPackagingReview_(sheet, columns, sheetRow, true);
        result.invalidRuleCount += 1;
        return;
      }

      const rowContext = buildPackagingRowContext_(row, firstRow, columns);
      const match = findPackagingRule_(rules, rowContext);

      if (!match.rule) {
        if (!match.conflict && unitDocument === unitUs) {
          writePackagingResult_(sheet, columns, sheetRow, sourceQuantity, '');
          clearPackagingCorrection_(sheet, columns, sheetRow);
          result.sameUnitCount += 1;
          return;
        }

        markPackagingReview_(sheet, columns, sheetRow, true);

        if (match.conflict) {
          result.conflictCount += 1;
        } else {
          result.missingRuleCount += 1;
        }

        return;
      }

      const calculatedQuantity = calculatePackagingQuantity_(sourceQuantity, unitUs, match.rule);

      if (calculatedQuantity === null) {
        markPackagingReview_(sheet, columns, sheetRow, true);
        result.invalidRuleCount += 1;
        result.invalidMessages.push(
          'строка ' +
            sheetRow +
            ' (' +
            String(row[columns['Наименование товара в УС'] - 1]).trim() +
            '): ' +
            describePackagingCalculationProblem_(sourceQuantity, unitUs, match.rule)
        );
        return;
      }

      writePackagingResult_(
        sheet,
        columns,
        sheetRow,
        calculatedQuantity,
        match.rule.id
      );
      clearPackagingCorrection_(sheet, columns, sheetRow);
      result.appliedCount += 1;
    });
  });

  return result;
}

function buildPackagingRules_(spreadsheet) {
  const sheet = spreadsheet.getSheetByName(CONFIG.packagingRulesSheetName);

  if (!sheet) {
    throw new Error('Не найден лист: ' + CONFIG.packagingRulesSheetName);
  }

  const columns = getColumnMapByHeaderRow_(sheet, CONFIG.packagingRulesHeaderRow);
  const requiredHeaders = [
    'ID правила',
    'Активность правила',
    'Приоритет правила',
    'Поставщик',
    'ИНН поставщика',
    'Код товара поставщика',
    'Название из документа',
    'Код товара УС',
    'Склад / назначение',
    'Ед. изм. документа',
    'Количество вложений',
    'Ед. изм. вложения',
    'Вес / объем единицы',
    'Ед. изм. веса/объема',
    'Сухой вес единицы',
    'Ед. изм. в УС',
    'Режим пересчета',
    'Коэффициент',
    'Округление',
    'Ручная проверка',
  ];
  requireColumns_(columns, requiredHeaders);

  const startRow = CONFIG.packagingRulesHeaderRow + 1;
  const lastRow = sheet.getLastRow();

  if (lastRow < startRow) {
    return [];
  }

  const values = sheet
    .getRange(startRow, 1, lastRow - startRow + 1, sheet.getLastColumn())
    .getValues();

  return values
    .map((row, index) => {
      return {
        sheetRow: startRow + index,
        id: String(row[columns['ID правила'] - 1]).trim(),
        activity: String(row[columns['Активность правила'] - 1]).trim(),
        priority: toCalculationNumber_(row[columns['Приоритет правила'] - 1]),
        supplier: normalizeProductSearchText_(row[columns['Поставщик'] - 1]),
        supplierInn: normalizeIdentifier_(row[columns['ИНН поставщика'] - 1]),
        supplierProductCode: normalizeIdentifier_(row[columns['Код товара поставщика'] - 1]),
        originalName: normalizeProductName_(row[columns['Название из документа'] - 1]),
        productCode: normalizeIdentifier_(row[columns['Код товара УС'] - 1]),
        destination: normalizeProductSearchText_(row[columns['Склад / назначение'] - 1]),
        unitDocument: normalizePackagingUnit_(row[columns['Ед. изм. документа'] - 1]),
        nestedQuantity: toCalculationNumber_(row[columns['Количество вложений'] - 1]),
        nestedUnit: normalizePackagingUnit_(row[columns['Ед. изм. вложения'] - 1]),
        unitWeightOrVolume: toCalculationNumber_(row[columns['Вес / объем единицы'] - 1]),
        parameterUnit: normalizePackagingUnit_(row[columns['Ед. изм. веса/объема'] - 1]),
        dryWeight: toCalculationNumber_(row[columns['Сухой вес единицы'] - 1]),
        unitUs: normalizePackagingUnit_(row[columns['Ед. изм. в УС'] - 1]),
        mode: String(row[columns['Режим пересчета'] - 1]).trim(),
        coefficient: toCalculationNumber_(row[columns['Коэффициент'] - 1]),
        rounding: String(row[columns['Округление'] - 1]).trim(),
        manualReview: isYesValue_(row[columns['Ручная проверка'] - 1]),
      };
    })
    .filter((rule) => rule.id !== '' && rule.activity === 'Активно' && rule.productCode !== '');
}

function buildPackagingRowContext_(row, firstRow, columns) {
  return {
    productCode: normalizeIdentifier_(row[columns['Код товара УС'] - 1]),
    supplier: normalizeProductSearchText_(getDocumentValue_(row, firstRow, columns, 'Поставщик')),
    supplierInn: normalizeIdentifier_(getDocumentValue_(row, firstRow, columns, 'ИНН Поставщика')),
    supplierProductCode: columns['Код товара поставщика']
      ? normalizeIdentifier_(row[columns['Код товара поставщика'] - 1])
      : '',
    originalName: normalizeProductName_(row[columns['Наименование товара из документа'] - 1]),
    destination: normalizeProductSearchText_(getDocumentValue_(row, firstRow, columns, 'Склад')),
    unitDocument: normalizePackagingUnit_(row[columns['Ед.изм. в документе'] - 1]),
  };
}

function findPackagingRule_(rules, context) {
  const candidates = rules
    .filter((rule) => {
      if (rule.productCode !== context.productCode) return false;
      if (rule.supplierInn !== '' && rule.supplierInn !== context.supplierInn) return false;
      if (rule.supplierInn === '' && rule.supplier !== '' && rule.supplier !== context.supplier) return false;
      if (rule.supplierProductCode !== '' && rule.supplierProductCode !== context.supplierProductCode) return false;
      if (rule.originalName !== '' && rule.originalName !== context.originalName) return false;
      if (rule.destination !== '' && rule.destination !== context.destination) return false;
      if (rule.unitDocument !== '' && rule.unitDocument !== context.unitDocument) return false;
      return true;
    })
    .map((rule) => {
      return {
        rule: rule,
        specificity:
          (rule.supplierInn !== '' ? 8 : 0) +
          (rule.supplierInn === '' && rule.supplier !== '' ? 4 : 0) +
          (rule.supplierProductCode !== '' ? 4 : 0) +
          (rule.originalName !== '' ? 4 : 0) +
          (rule.destination !== '' ? 3 : 0) +
          (rule.unitDocument !== '' ? 1 : 0),
        priority: rule.priority === null ? 999999 : rule.priority,
      };
    })
    .sort((left, right) => {
      if (left.specificity !== right.specificity) return right.specificity - left.specificity;
      return left.priority - right.priority;
    });

  if (candidates.length === 0) {
    return { rule: null, conflict: false };
  }

  if (
    candidates.length > 1 &&
    candidates[0].specificity === candidates[1].specificity &&
    candidates[0].priority === candidates[1].priority
  ) {
    return { rule: null, conflict: true };
  }

  return { rule: candidates[0].rule, conflict: false };
}

function calculatePackagingQuantity_(sourceQuantity, unitUs, rule) {
  if (rule.manualReview || rule.mode === 'Ручная проверка') {
    return null;
  }

  let result = null;

  if (rule.mode === 'Без пересчета') {
    result = sourceQuantity;
  } else if (rule.mode === 'По количеству вложений') {
    if (
      rule.nestedQuantity === null ||
      rule.nestedQuantity <= 0 ||
      rule.nestedUnit === '' ||
      rule.nestedUnit !== unitUs
    ) {
      return null;
    }

    result = sourceQuantity * rule.nestedQuantity;
  } else if (rule.mode === 'По весу' || rule.mode === 'По объему') {
    if (rule.unitWeightOrVolume === null || rule.unitWeightOrVolume <= 0) {
      return null;
    }

    const convertedValue = convertPackagingAmount_(
      rule.unitWeightOrVolume,
      rule.parameterUnit,
      unitUs
    );
    if (convertedValue === null) return null;
    result = sourceQuantity * convertedValue;
  } else if (rule.mode === 'По сухому весу') {
    if (rule.dryWeight === null || rule.dryWeight <= 0) {
      return null;
    }

    const dryWeightUnit = rule.unitUs || rule.parameterUnit;
    const convertedDryWeight = convertPackagingAmount_(rule.dryWeight, dryWeightUnit, unitUs);
    if (convertedDryWeight === null) return null;
    result = sourceQuantity * convertedDryWeight;
  } else if (rule.mode === 'По коэффициенту') {
    if (rule.coefficient === null || rule.coefficient <= 0) {
      return null;
    }

    result = sourceQuantity * rule.coefficient;
  } else if (rule.mode === 'По среднему весу штуки') {
    const averageWeight = rule.coefficient !== null ? rule.coefficient : rule.unitWeightOrVolume;

    if (averageWeight === null || averageWeight <= 0) {
      return null;
    }

    const convertedAverageWeight = convertPackagingAmount_(averageWeight, rule.parameterUnit, unitUs);
    if (convertedAverageWeight === null) return null;
    result = sourceQuantity * convertedAverageWeight;
  }

  if (result === null || !isFinite(result) || result < 0) {
    return null;
  }

  return applyPackagingRounding_(result, rule.rounding);
}

function describePackagingCalculationProblem_(sourceQuantity, unitUs, rule) {
  if (rule.manualReview || rule.mode === 'Ручная проверка') {
    return 'правило требует ручной проверки';
  }

  if (rule.mode === 'По сухому весу') {
    const dryWeightUnit = rule.unitUs || rule.parameterUnit;
    return (
      'сухой вес=' +
      String(rule.dryWeight) +
      ', ед. сухого веса=' +
      (dryWeightUnit || 'пусто') +
      ', ед. УС строки=' +
      (unitUs || 'пусто') +
      ', количество документа=' +
      String(sourceQuantity)
    );
  }

  return 'режим=' + rule.mode + ', правило=' + rule.id;
}

function convertPackagingAmount_(value, sourceUnit, targetUnit) {
  if (sourceUnit === '' || targetUnit === '') return null;
  if (sourceUnit === targetUnit) return value;
  if (sourceUnit === 'г' && targetUnit === 'кг') return value / 1000;
  if (sourceUnit === 'кг' && targetUnit === 'г') return value * 1000;
  if (sourceUnit === 'мл' && targetUnit === 'л') return value / 1000;
  if (sourceUnit === 'л' && targetUnit === 'мл') return value * 1000;
  return null;
}

function applyPackagingRounding_(value, rounding) {
  if (rounding === 'До целого') return Math.round(value);
  if (rounding === '1 знак') return Math.round(value * 10) / 10;
  if (rounding === '2 знака') return Math.round(value * 100) / 100;
  if (rounding === '3 знака') return Math.round(value * 1000) / 1000;
  return value;
}

function normalizePackagingUnit_(value) {
  const unit = normalizeUnit_(value);

  if (unit === 'килограмма' || unit === 'килограммов') return 'кг';
  if (unit === 'гр' || unit === 'грамм' || unit === 'граммы') return 'г';
  if (unit === 'грамма' || unit === 'граммов') return 'г';
  if (unit === 'литра' || unit === 'литров') return 'л';
  if (unit === 'миллилитр' || unit === 'миллилитры') return 'мл';
  if (unit === 'миллилитра' || unit === 'миллилитров') return 'мл';
  if (unit === 'штук') return 'шт';
  if (unit === 'упаковка' || unit === 'упаковки') return 'упак';
  if (unit === 'упаковку' || unit === 'упаковок') return 'упак';
  if (unit === 'пачка' || unit === 'пачки') return 'пач';
  if (unit === 'пачку' || unit === 'пачек') return 'пач';
  if (unit === 'бутылка' || unit === 'бутылки') return 'бут';
  if (unit === 'бутылку' || unit === 'бутылок') return 'бут';
  if (unit === 'банка' || unit === 'банки') return 'бан';
  if (unit === 'банку' || unit === 'банок') return 'бан';
  if (unit === 'рулон' || unit === 'рулоны') return 'рул';
  if (unit === 'рулона' || unit === 'рулонов') return 'рул';

  return unit;
}

function normalizeIdentifier_(value) {
  return String(value).replace(/[\s ]/g, '').trim().toLowerCase();
}

function getDocumentValue_(row, firstRow, columns, header) {
  if (!columns[header]) return '';
  const rowValue = row[columns[header] - 1];
  return rowValue !== '' && rowValue !== null ? rowValue : firstRow[columns[header] - 1];
}

function isManualQuantity_(value) {
  if (value === true || value === 1) return true;
  const normalized = String(value).trim().toLowerCase();
  return normalized === 'да' || normalized === 'true' || normalized === 'истина' || normalized === '1';
}

function isYesValue_(value) {
  return String(value).trim().toLowerCase() === 'да' || value === true;
}

function writePackagingResult_(sheet, columns, sheetRow, quantity, ruleId) {
  sheet.getRange(sheetRow, columns['Кол-во в УС']).setValue(quantity);
  sheet.getRange(sheetRow, columns['ID правила фасовки']).setValue(ruleId || '');
}

function markPackagingReview_(sheet, columns, sheetRow, clearCalculatedValues) {
  const correctionCell = sheet.getRange(sheetRow, columns['Корректировка']);
  const currentCorrection = String(correctionCell.getValue()).trim();

  if (currentCorrection === '' || currentCorrection === 'Фасовка') {
    correctionCell.setValue('Фасовка').setBackground(COLORS.review);
  }

  if (clearCalculatedValues) {
    sheet.getRange(sheetRow, columns['Кол-во в УС']).clearContent();
    sheet.getRange(sheetRow, columns['ID правила фасовки']).clearContent();
  }
}

function clearPackagingCorrection_(sheet, columns, sheetRow) {
  const correctionCell = sheet.getRange(sheetRow, columns['Корректировка']);

  if (String(correctionCell.getValue()).trim() === 'Фасовка') {
    correctionCell.clearContent().setBackground(COLORS.empty);
  }
}

function requirePackagingInvoiceColumns_(columns) {
  requireColumns_(columns, [
    'Корректировка',
    'Поставщик',
    'ИНН Поставщика',
    'Склад',
    'Наименование товара из документа',
    'Код товара УС',
    'Ед.изм. в документе',
    'Ед.изм. в УС',
    'Кол-во в документе',
    'Кол-во в УС',
    'Количество исправлено вручную',
    'ID правила фасовки',
  ]);
}

function calculateUsPricesForDocuments_(sheet, values, columns, documents) {
  requireColumns_(columns, ['Кол-во в УС', 'Общая стоимость', 'Цена в УС']);

  let calculatedCount = 0;
  let missingInputCount = 0;

  documents.forEach((document) => {
    const documentRows = values.slice(document.startIndex, document.endIndex + 1);
    const firstSheetRow = CONFIG.startRow + document.startIndex;

    const priceValues = documentRows.map((row) => {
      if (!isLoadableExportProductRow_(row, columns)) {
        return [row[columns['Цена в УС'] - 1] || ''];
      }

      const quantityUs = toCalculationNumber_(row[columns['Кол-во в УС'] - 1]);
      const totalCost = toCalculationNumber_(row[columns['Общая стоимость'] - 1]);

      if (quantityUs === null || quantityUs <= 0 || totalCost === null) {
        missingInputCount += 1;
        return [''];
      }

      calculatedCount += 1;
      return [totalCost / quantityUs];
    });

    if (priceValues.length > 0) {
      sheet
        .getRange(firstSheetRow, columns['Цена в УС'], priceValues.length, 1)
        .setValues(priceValues);
    }
  });

  return {
    calculatedCount: calculatedCount,
    missingInputCount: missingInputCount,
  };
}

function toCalculationNumber_(value) {
  if (typeof value === 'number') {
    return isFinite(value) ? value : null;
  }

  const normalized = String(value)
    .replace(/[\s ]/g, '')
    .replace(',', '.')
    .trim();

  if (normalized === '') {
    return null;
  }

  const number = Number(normalized);
  return isFinite(number) ? number : null;
}

function getProductReadiness_(documentRows, columns) {
  const loadableRows = documentRows.filter((row) => {
    return isLoadableExportProductRow_(row, columns) && !isProductSkipRow_(row, columns);
  });

  if (loadableRows.length === 0) {
    return {
      hasProductProblem: true,
      hasWaitCreate: false,
      hasNoLoadableRows: true,
    };
  }

  const hasWaitCreate = loadableRows.some((row) => {
    return getProductMatchStatus_(row, columns) === PRODUCT_MATCH_STATUS.WAIT_CREATE;
  });

  const hasBlockingProductStatus = loadableRows.some((row) => {
    const status = getProductMatchStatus_(row, columns);

    return (
      status === PRODUCT_MATCH_STATUS.NEED_CHOICE ||
      status === PRODUCT_MATCH_STATUS.NEW ||
      status === PRODUCT_MATCH_STATUS.WAIT_CREATE
    );
  });

  const hasMissingProductData = loadableRows.some((row) => {
    const productName = String(row[columns['Наименование товара в УС'] - 1]).trim();
    const productCode = String(row[columns['Код товара УС'] - 1]).trim();

    return productName === '' || productCode === '';
  });

  return {
    hasProductProblem: hasBlockingProductStatus || hasMissingProductData,
    hasWaitCreate: hasWaitCreate,
    hasNoLoadableRows: false,
  };
}

function isResolvedProductCorrection_(row, columns, correction) {
  if (correction === 'Фасовка') {
    const manualQuantity = columns['Количество исправлено вручную']
      ? isManualQuantity_(row[columns['Количество исправлено вручную'] - 1])
      : false;
    const quantityUs = toCalculationNumber_(row[columns['Кол-во в УС'] - 1]);

    return manualQuantity && quantityUs !== null && quantityUs >= 0;
  }

  if (correction !== 'Сопоставление' && correction !== 'Нет в справочнике') {
    return false;
  }

  const productName = String(row[columns['Наименование товара в УС'] - 1]).trim();
  const productCode = String(row[columns['Код товара УС'] - 1]).trim();
  const productMatchStatus = getProductMatchStatus_(row, columns);

  return (
    productName !== '' &&
    productCode !== '' &&
    (productMatchStatus === PRODUCT_MATCH_STATUS.FOUND ||
      productMatchStatus === PRODUCT_MATCH_STATUS.MANUAL)
  );
}

function isProductSkipRow_(row, columns) {
  return getProductMatchStatus_(row, columns) === PRODUCT_MATCH_STATUS.SKIP;
}

function isLoadableExportProductRow_(row, columns) {
  const documentProductName = columns['Наименование товара из документа']
    ? String(row[columns['Наименование товара из документа'] - 1]).trim()
    : '';
  const productName = String(row[columns['Наименование товара в УС'] - 1]).trim();
  const productCode = String(row[columns['Код товара УС'] - 1]).trim();

  return documentProductName !== '' || productName !== '' || productCode !== '';
}

function countLoadableProductRows_(rows, columns) {
  return rows.filter((row) => isLoadableExportProductRow_(row, columns)).length;
}

function getExportValue_(row, firstRow, columns, header) {
  const value = row[columns[header] - 1];

  if (value !== '' && value !== null) {
    return value;
  }

  if (isDocumentLevelExportHeader_(header)) {
    return firstRow[columns[header] - 1];
  }

  return '';
}

function isDocumentLevelExportHeader_(header) {
  return [
    'Дата документа',
    '№ Документа',
    'Поставщик',
    'ИНН Поставщика',
    'Получатель',
    'Торговая точка',
    'Склад',
    'Основание',
    'Сумма накладной',
  ].includes(header);
}

function isPrepareCreateDecision_(decision) {
  const normalizedDecision = String(decision).trim().toLowerCase();

  return normalizedDecision === 'подготовить к созданию' || normalizedDecision === 'подготовить к создани';
}

function setPrepareCreateDecision_(cell) {
  const validation = cell.getDataValidation();
  let decisionValue = 'Подготовить к созданию';

  if (validation) {
    const criteriaValues = validation.getCriteriaValues();
    const options = criteriaValues.length > 0 && Array.isArray(criteriaValues[0]) ? criteriaValues[0] : [];
    const matchingOption = options.find((option) => isPrepareCreateDecision_(option));

    if (matchingOption) {
      decisionValue = matchingOption;
    }
  }

  try {
    cell.setValue(decisionValue);
  } catch (error) {
    cell.clearDataValidations();
    cell.setValue(decisionValue);

    if (validation) {
      cell.setDataValidation(validation);
    }
  }
}

function getProductMatchStatus_(row, columns) {
  return String(row[columns['Статус сопоставления товара'] - 1]).trim();
}

function evaluateBlockedRowStatus_(row, columns) {
  const currentStatus = String(row[columns['Статус строки'] - 1]).trim();
  const correction = String(row[columns['Корректировка'] - 1]).trim();

  if (currentStatus === ROW_STATUS.SENT) {
    return { status: ROW_STATUS.SENT, color: COLORS.loaded, correction: correction };
  }

  if (correction === 'Ошибка OCR') {
    return { status: ROW_STATUS.ERROR, color: COLORS.notReady, correction: correction };
  }

  if (MANUAL_CORRECTIONS.includes(correction)) {
    return { status: ROW_STATUS.MANUAL, color: COLORS.review, correction: correction };
  }

  return { status: ROW_STATUS.RECOGNIZED, color: COLORS.check, correction: correction };
}

function evaluateRowStatus_(row, columns) {
  const currentStatus = String(row[columns['Статус строки'] - 1]).trim();
  const correction = String(row[columns['Корректировка'] - 1]).trim();
  const duplicate = String(row[columns['Дубль'] - 1]).trim();

  if (currentStatus === ROW_STATUS.SENT) {
    return { status: ROW_STATUS.SENT, color: COLORS.loaded, correction: correction };
  }

  if (correction === 'Ошибка OCR') {
    return { status: ROW_STATUS.ERROR, color: COLORS.notReady, correction: correction };
  }

  if (duplicate === 'Да' || duplicate === '?') {
    return { status: ROW_STATUS.RECOGNIZED, color: COLORS.check, correction: correction };
  }

  if (currentStatus === ROW_STATUS.RETURN && correction === '') {
    return { status: ROW_STATUS.READY, color: COLORS.ready, correction: '' };
  }

  if (MANUAL_CORRECTIONS.includes(correction)) {
    return { status: ROW_STATUS.MANUAL, color: COLORS.review, correction: correction };
  }

  if (
    currentStatus === ROW_STATUS.RECOGNIZED ||
    currentStatus === ROW_STATUS.MANUAL ||
    currentStatus === ROW_STATUS.READY ||
    currentStatus === ''
  ) {
    return { status: ROW_STATUS.READY, color: COLORS.ready, correction: '' };
  }

  if (currentStatus === ROW_STATUS.RETURN) {
    return { status: ROW_STATUS.RETURN, color: COLORS.returnReview, correction: correction };
  }

  return { status: currentStatus, color: getRowStatusColor_(currentStatus), correction: correction };
}

function getRowStatusColor_(status) {
  if (status === ROW_STATUS.RECOGNIZED) return COLORS.check;
  if (status === ROW_STATUS.MANUAL) return COLORS.review;
  if (status === ROW_STATUS.ERROR) return COLORS.notReady;
  if (status === ROW_STATUS.READY) return COLORS.ready;
  if (status === ROW_STATUS.SENT) return COLORS.loaded;
  if (status === ROW_STATUS.RETURN) return COLORS.returnReview;
  return COLORS.empty;
}

function markDocumentAsLoaded_(sheet, columns, document) {
  const rowCount = document.endIndex - document.startIndex + 1;
  const firstSheetRow = CONFIG.startRow + document.startIndex;

  const checkboxValues = Array.from({ length: rowCount }, () => [false]);

  sheet.getRange(firstSheetRow, columns['Статус загрузки']).setValue(LOAD_STATUS.LOADED);
  sheet.getRange(firstSheetRow, columns['Статус загрузки']).setBackground(COLORS.loaded);
  sheet.getRange(firstSheetRow, columns['Статус строки']).setValue(ROW_STATUS.SENT);
  sheet.getRange(firstSheetRow, columns['Статус строки']).setBackground(COLORS.loaded);
  sheet.getRange(firstSheetRow, columns['Загрузка'], rowCount, 1).setValues(checkboxValues);

  if (rowCount > 1) {
    sheet.getRange(firstSheetRow + 1, columns['Статус загрузки'], rowCount - 1, 1).clearContent().setBackground(COLORS.empty);
    sheet.getRange(firstSheetRow + 1, columns['Статус строки'], rowCount - 1, 1).clearContent().setBackground(COLORS.empty);
  }
}

function clearDocumentCheckboxes_(sheet, columns, document) {
  const rowCount = document.endIndex - document.startIndex + 1;
  const firstSheetRow = CONFIG.startRow + document.startIndex;
  const checkboxValues = Array.from({ length: rowCount }, () => [false]);

  sheet.getRange(firstSheetRow, columns['Загрузка'], rowCount, 1).setValues(checkboxValues);
}

function getDocumentBlocks_(values, columns) {
  const blocks = [];
  let currentStartIndex = null;

  values.forEach((row, index) => {
    const hasDocumentStart =
      row[columns['Дата документа'] - 1] !== '' ||
      row[columns['№ Документа'] - 1] !== '' ||
      row[columns['Поставщик'] - 1] !== '';

    if (!hasDocumentStart) {
      return;
    }

    if (currentStartIndex !== null) {
      blocks.push({
        startIndex: currentStartIndex,
        endIndex: index - 1,
      });
    }

    currentStartIndex = index;
  });

  if (currentStartIndex !== null) {
    blocks.push({
      startIndex: currentStartIndex,
      endIndex: values.length - 1,
    });
  }

  return blocks;
}

function getColumnMap_(sheet) {
  const headers = sheet
    .getRange(CONFIG.headerRow, 1, 1, sheet.getLastColumn())
    .getDisplayValues()[0];

  const columns = {};

  headers.forEach((header, index) => {
    const name = String(header).trim();

    if (name !== '') {
      columns[name] = index + 1;
    }
  });

  return columns;
}

function getColumnMapByHeaderRow_(sheet, headerRow) {
  const headers = sheet
    .getRange(headerRow, 1, 1, sheet.getLastColumn())
    .getDisplayValues()[0];

  const columns = {};

  headers.forEach((header, index) => {
    const name = String(header).trim();

    if (name !== '') {
      columns[name] = index + 1;
    }
  });

  return columns;
}

function getProductDirectoryColumnMap_(sheet) {
  const sourceColumns = getColumnMapByHeaderRow_(sheet, 1);
  const columns = Object.assign({}, sourceColumns);

  columns['Наименование'] = sourceColumns['Наименование'] || sourceColumns['Наименование товара в УС'];
  columns['Код в УС'] = sourceColumns['Код в УС'] || sourceColumns['Код товара УС'];
  columns['Ед. изм.'] = sourceColumns['Ед. изм.'] || sourceColumns['Ед. изм. в УС'];

  requireColumns_(columns, ['Наименование', 'Код в УС', 'Ед. изм.']);

  return columns;
}

function getOrCreateSheet_(spreadsheet, sheetName) {
  const existingSheet = spreadsheet.getSheetByName(sheetName);

  if (existingSheet) {
    return existingSheet;
  }

  return spreadsheet.insertSheet(sheetName);
}

function uniqueValues_(values) {
  const result = [];
  const seen = {};

  values.forEach((value) => {
    const text = String(value).trim();

    if (text === '' || seen[text]) {
      return;
    }

    seen[text] = true;
    result.push(text);
  });

  return result;
}

function getActualData_(sheet, columns) {
  const lastRow = sheet.getLastRow();

  if (lastRow < CONFIG.startRow) {
    return { values: [] };
  }

  const values = sheet
    .getRange(CONFIG.startRow, 1, lastRow - CONFIG.startRow + 1, sheet.getLastColumn())
    .getValues();

  const significantColumnNumbers = Object.keys(columns)
    .filter((header) => header !== 'Загрузка')
    .map((header) => columns[header]);

  let actualLastIndex = -1;

  values.forEach((row, index) => {
    const hasData = significantColumnNumbers.some((columnNumber) => {
      const value = row[columnNumber - 1];
      return value !== '' && value !== null && value !== false;
    });

    if (hasData) {
      actualLastIndex = index;
    }
  });

  if (actualLastIndex === -1) {
    return { values: [] };
  }

  return {
    values: values.slice(0, actualLastIndex + 1),
  };
}

function requireBaseColumns_(columns) {
  requireColumns_(columns, [
    'Загрузка',
    'Статус загрузки',
    'Статус строки',
    'Корректировка',
    'Дубль',
    'Дата документа',
    '№ Документа',
    'Поставщик',
    'Наименование товара в УС',
    'Код товара УС',
    'Статус сопоставления товара',
    'Кол-во в УС',
    'Общая стоимость',
    'Цена в УС',
  ]);
}

function requireColumns_(columns, requiredHeaders) {
  const missingHeaders = requiredHeaders.filter((header) => !columns[header]);

  if (missingHeaders.length > 0) {
    throw new Error('Не найдены колонки: ' + missingHeaders.join(', '));
  }
}

function ensureTargetHeaders_(targetSheet, exportHeaders) {
  const firstRowValues = targetSheet
    .getRange(1, 1, 1, exportHeaders.length)
    .getDisplayValues()[0];

  const hasHeaders = firstRowValues.some((value) => String(value).trim() !== '');

  if (!hasHeaders) {
    targetSheet.getRange(1, 1, 1, exportHeaders.length).setValues([exportHeaders]);
    targetSheet.getRange(1, 1, 1, exportHeaders.length).setFontWeight('bold');
  }
}

function formatTargetSheet_(targetSheet, startRow, rowCount, exportHeaders) {
  const formatByHeader = {
    'Ставка НДС': '0%',
    'Сумма НДС': '0.00',
    'Общая стоимость': '0.00',
    'Сумма накладной': '0.00',
    'Кол-во в УС': '0.000',
    'Цена в УС': '0.00',
  };

  exportHeaders.forEach((header, index) => {
    const format = formatByHeader[header];

    if (format) {
      targetSheet.getRange(startRow, index + 1, rowCount, 1).setNumberFormat(format);
    }
  });
}

function restoreInvoiceNumberFormats() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(CONFIG.sourceSheetName);
  const columns = getColumnMap_(sheet);
  const data = getActualData_(sheet, columns);

  if (data.values.length === 0) {
    return;
  }

  const formats = {
    'Ставка НДС': '0%',
    'Сумма НДС': '0.00',
    'Общая стоимость': '0.00',
    'Сумма накладной': '0.00',
    'Стоимость без НДС': '0.00',
    'Кол-во в УС': '0.000',
    'Цена в УС': '0.00',
    'Цена за ед-цу': '0.00',
  };

  const skippedHeaders = [];

  Object.keys(formats).forEach((header) => {
    if (!columns[header]) {
      return;
    }

    try {
      sheet
        .getRange(CONFIG.startRow, columns[header], data.values.length, 1)
        .setNumberFormat(formats[header]);
    } catch (error) {
      skippedHeaders.push(header);
    }
  });

  let message = 'Восстановление форматов завершено.';

  if (skippedHeaders.length > 0) {
    message +=
      '\nФормат этих столбцов управляется типом данных таблицы и не изменялся скриптом: ' +
      skippedHeaders.join(', ');
  }

  SpreadsheetApp.getUi().alert(message);
}

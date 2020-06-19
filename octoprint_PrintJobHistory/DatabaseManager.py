# coding=utf-8
from __future__ import absolute_import

import datetime
import logging
import os
import shutil
import sqlite3

from octoprint_PrintJobHistory.WrappedLoggingHandler import WrappedLoggingHandler
from octoprint_PrintJobHistory.models.FilamentModel import FilamentModel
from octoprint_PrintJobHistory.models.PrintJobModel import PrintJobModel
from octoprint_PrintJobHistory.models.PluginMetaDataModel import PluginMetaDataModel
from octoprint_PrintJobHistory.models.TemperatureModel import TemperatureModel
from peewee import *


FORCE_CREATE_TABLES = False
# SQL_LOGGING = True

CURRENT_DATABASE_SCHEME_VERSION = 3

# List all Models
MODELS = [PluginMetaDataModel, PrintJobModel, FilamentModel, TemperatureModel]


class DatabaseManager(object):

	def __init__(self, parentLogger, sqlLoggingEnabled, externalDatabase):
		self.sqlLoggingEnabled = sqlLoggingEnabled
		self._logger = logging.getLogger(parentLogger.name + "." + self.__class__.__name__)
		self._sqlLogger = logging.getLogger(parentLogger.name + "." + self.__class__.__name__ + ".SQL")

		self._database = None
		self._databaseFileLocation = None
		self._sendDataToClient = None

		self.externalDatabase = externalDatabase

	################################################################################################## private functions

	def _createOrUpgradeSchemeIfNecessary(self):
		schemeVersionFromDatabaseModel = None
		try:
			schemeVersionFromDatabaseModel = PluginMetaDataModel.get(PluginMetaDataModel.key == PluginMetaDataModel.KEY_DATABASE_SCHEME_VERSION)
			pass
		except Exception as e:
			errorMessage = str(e)
			if errorMessage.startswith("no such table") or (self.externalDatabase.get('enabled') and errorMessage.__contains__("does not exist")):  # "no such table" didn't work for PostgreSQL when testing if tables exist in the database
				self._logger.info("Create database-table, because didn't exists")
				self._createDatabaseTables()
			else:
				self._logger.error(str(e))

		if not schemeVersionFromDatabaseModel == None:
			currentDatabaseSchemeVersion = int(schemeVersionFromDatabaseModel.value)
			if (currentDatabaseSchemeVersion < CURRENT_DATABASE_SCHEME_VERSION):
				# evautate upgrade steps (from 1-2 , 1...6)
				self._logger.info("We need to upgrade the database scheme from: '" + str(currentDatabaseSchemeVersion) + "' to: '" + str(CURRENT_DATABASE_SCHEME_VERSION) + "'")

				try:
					self.backupDatabaseFile(self._databasePath)
					self._upgradeDatabase(currentDatabaseSchemeVersion, CURRENT_DATABASE_SCHEME_VERSION)
				except Exception as e:
					self._logger.error("Error during database upgrade!!!!")
					self._logger.exception(e)
					return
				self._logger.info("Database-scheme successfully upgraded.")
		pass

	def _upgradeDatabase(self,currentDatabaseSchemeVersion, targetDatabaseSchemeVersion):

		migrationFunctions = [self._upgradeFrom1To2, self._upgradeFrom2To3, self._upgradeFrom3To4, self._upgradeFrom4To5]

		for migrationMethodIndex in range(currentDatabaseSchemeVersion -1, targetDatabaseSchemeVersion -1):
			self._logger.info("Database migration from '" + str(migrationMethodIndex + 1) + "' to '" + str(migrationMethodIndex + 2) + "'")
			migrationFunctions[migrationMethodIndex]()
			pass
		pass

	def _upgradeFrom4To5(self):
		self._logger.info(" Starting 4 -> 5")

	def _upgradeFrom3To4(self):
		self._logger.info(" Starting 3 -> 4")

	def _upgradeFrom2To3(self):
		self._logger.info(" Starting 2 -> 3")
		# What is changed:
		# - PrintJobModel:
		# 	- Add Column: slicerSettingsAsText

		connection = sqlite3.connect(self._databaseFileLocation)
		cursor = connection.cursor()

		sql = """
		PRAGMA foreign_keys=off;
		BEGIN TRANSACTION;

			ALTER TABLE 'pjh_printjobmodel' ADD 'slicerSettingsAsText' TEXT;

				UPDATE 'pjh_pluginmetadatamodel' SET value=3 WHERE key='databaseSchemeVersion';
		COMMIT;
		PRAGMA foreign_keys=on;
		"""
		cursor.executescript(sql)

		connection.close()
		self._logger.info(" Successfully 2 -> 3")
		pass


	def _upgradeFrom1To2(self):
		self._logger.info(" Starting 1 -> 2")
		# What is changed:
		# - PrintJobModel: Add Column fileOrigin
		# - FilamentModel: Several ColumnTypes were wrong
		connection = sqlite3.connect(self._databaseFileLocation)
		cursor = connection.cursor()

		sql = """
		PRAGMA foreign_keys=off;
		BEGIN TRANSACTION;

			ALTER TABLE 'pjh_printjobmodel' ADD 'fileOrigin' VARCHAR(255);

			ALTER TABLE 'pjh_filamentmodel' RENAME TO 'pjh_filamentmodel_old';
			CREATE TABLE "pjh_filamentmodel" (
				"databaseId" INTEGER NOT NULL PRIMARY KEY,
				"created" DATETIME NOT NULL,
				"printJob_id" INTEGER NOT NULL,
				"profileVendor" VARCHAR(255),
				"diameter" REAL,
				"density" REAL,
				"material" VARCHAR(255),
				"spoolName" VARCHAR(255),
				"spoolCost" VARCHAR(255),
				"spoolCostUnit" VARCHAR(255),
				"spoolWeight" REAL,
				"usedLength" REAL,
				"calculatedLength" REAL,
				"usedWeight" REAL,
				"usedCost" REAL,
				FOREIGN KEY ("printJob_id") REFERENCES "pjh_printjobmodel" ("databaseId") ON DELETE CASCADE);

				INSERT INTO 'pjh_filamentmodel' (databaseId, created, printJob_id, profileVendor, diameter, density, material, spoolName, spoolCost, spoolCostUnit, spoolWeight, usedLength, calculatedLength, usedWeight, usedCost)
				  SELECT databaseId, created, printJob_id, profileVendor, diameter, density, material, spoolName, spoolCost, spoolCostUnit, spoolWeight, usedLength, calculatedLength, usedWeight, usedCost
				  FROM 'pjh_filamentmodel_old';

				DROP TABLE 'pjh_filamentmodel_old';

				UPDATE 'pjh_pluginmetadatamodel' SET value=2 WHERE key='databaseSchemeVersion';
		COMMIT;
		PRAGMA foreign_keys=on;
		"""
		cursor.executescript(sql)

		connection.close()
		pass



	def _createDatabaseTables(self):
		self._database.connect(reuse_if_open=True)
		self._database.drop_tables(MODELS)
		self._database.create_tables(MODELS)

		PluginMetaDataModel.create(key=PluginMetaDataModel.KEY_DATABASE_SCHEME_VERSION, value=CURRENT_DATABASE_SCHEME_VERSION)
		self._database.close()
		self._logger.info("Database tables created")

	################################################################################################### public functions
	# datapasePath '/Users/o0632/Library/Application Support/OctoPrint/data/PrintJobHistory'
	def initDatabase(self, databasePath, sendErrorMessageToClient):
		self._logger.info("Init DatabaseManager")
		self.sendErrorMessageToClient = sendErrorMessageToClient
		self._databasePath = databasePath
		self._databaseFileLocation = os.path.join(databasePath, "printJobHistory.db")

		self._logger.info("Creating database in: " + str(self._databaseFileLocation))


		import logging
		logger = logging.getLogger('peewee')
		# we need only the single logger without parent
		logger.parent = None
		# logger.addHandler(logging.StreamHandler())
		# activate SQL logging on PEEWEE side and on PLUGIN side

		# logger.setLevel(logging.DEBUG)
		# self._sqlLogger.setLevel(logging.DEBUG)
		self.showSQLLogging(self.sqlLoggingEnabled)

		wrappedHandler = WrappedLoggingHandler(self._sqlLogger)
		logger.addHandler(wrappedHandler)

		self._createDatabase(FORCE_CREATE_TABLES)

		pass

	def showSQLLogging(self, enabled):
		import logging
		logger = logging.getLogger('peewee')

		if (enabled):
			logger.setLevel(logging.DEBUG)
			self._sqlLogger.setLevel(logging.DEBUG)
		else:
			logger.setLevel(logging.ERROR)
			self._sqlLogger.setLevel(logging.ERROR)


	def backupDatabaseFile(self, backupFolder):
		now = datetime.datetime.now()
		currentDate = now.strftime("%Y%m%d-%H%M")
		backupDatabaseFileName = "printJobHistory-backup-"+currentDate+".db"
		backupDatabaseFilePath = os.path.join(backupFolder, backupDatabaseFileName)
		if not os.path.exists(backupDatabaseFilePath):
			shutil.copy(self._databaseFileLocation, backupDatabaseFilePath)
			self._logger.info("Backup of printjobhistory database created '"+backupDatabaseFilePath+"'")
		else:
			self._logger.warn("Backup of printjobhistory database ('" + backupDatabaseFilePath + "') is already present. No backup created.")
		return backupDatabaseFilePath


	def _createDatabase(self, forceCreateTables):

		if self.externalDatabase.get('enabled'):
			self._database = PostgresqlDatabase(
				self.externalDatabase.get('database_name'),
				user=self.externalDatabase.get('username'),
				password=self.externalDatabase.get('password'),
				host=self.externalDatabase.get('host'),
				port=self.externalDatabase.get('port'),
				# NOTE 6.4.2020 1:55PM The next two lines are needed bc when a test query is done to see if the tables exist in the database, an error is thrown if they aren't and will crash when the next query is done. So PostgreSQL needs the auto rollback so the tables can be created after the test results in an error since there were no tables at first.
				autocommit=True,
				autorollback=True
			)
		else:
			self._database = SqliteDatabase(self._databaseFileLocation)

		DatabaseManager.db = self._database
		self._database.bind(MODELS)

		if forceCreateTables:
			self._logger.info("Creating new database-tables, because FORCE == TRUE!")
			self._createDatabaseTables()
		else:
			# check, if we need an scheme upgrade
			self._logger.info("Check if database-scheme upgrade needed.")
			self._createOrUpgradeSchemeIfNecessary()
		self._logger.info("Done DatabaseManager.createDatabase")


	def getDatabaseFileLocation(self):
		return self._databaseFileLocation

	def reCreateDatabase(self):
		self._logger.info("ReCreating Database")
		self._createDatabase(True)

	def insertPrintJob(self, printJobModel):
		databaseId = None
		with self._database.atomic() as transaction:  # Opens new transaction.
			try:
				printJobModel.save()
				databaseId = printJobModel.get_id()
				# save all relations
				# - Filament
				for filamentModel in printJobModel.getFilamentModels():
					filamentModel.printJob = printJobModel
					filamentModel.save()
				# - Temperature
				for temperatureModel in printJobModel.getTemperatureModels():
					temperatureModel.printJob = printJobModel
					temperatureModel.save()
				# do expicit commit
				transaction.commit()
			except Exception as e:
				# Because this block of code is wrapped with "atomic", a
				# new transaction will begin automatically after the call
				# to rollback().
				transaction.rollback()
				self._logger.exception("Could not insert printJob into database:" + str(e))

				self.sendErrorMessageToClient("PJH-DatabaseManager", "Could not insert the printjob into the database. See OctoPrint.log for details!")
			pass

		return databaseId

	def updatePrintJob(self, printJobModel):
		with self._database.atomic() as transaction:  # Opens new transaction.
			try:
				printJobModel.save()
				databaseId = printJobModel.get_id()
				# save all relations
				# - Filament
				for filamentModel in printJobModel.getFilamentModels():
					filamentModel.save()

				# # - Temperature
				# for temperatureModel in printJobModel.getTemperatureModels():
				# 	temperatureModel.printJob = printJobModel
				# 	temperatureModel.save()
			except Exception as e:
				# Because this block of code is wrapped with "atomic", a
				# new transaction will begin automatically after the call
				# to rollback().
				transaction.rollback()
				self._logger.exception("Could not update printJob into database:" + str(e))
				self.sendErrorMessageToClient("PJH-DatabaseManager", "Could not update the printjob ('"+ printJobModel.fileName +"') into the database. See OctoPrint.log for details!")
			pass

	def countPrintJobsByQuery(self, tableQuery):

		filterName = tableQuery["filterName"]

		myQuery = PrintJobModel.select()
		if (filterName == "onlySuccess"):
			myQuery = myQuery.where(PrintJobModel.printStatusResult == "success")
		elif (filterName == "onlyFailed"):
			myQuery = myQuery.where(PrintJobModel.printStatusResult != "success")

		return myQuery.count()


	def loadPrintJobsByQuery(self, tableQuery):
		offset = int(tableQuery["from"])
		limit = int(tableQuery["to"])
		sortColumn = tableQuery["sortColumn"]
		sortOrder = tableQuery["sortOrder"]
		filterName = tableQuery["filterName"]

		myQuery = PrintJobModel.select().offset(offset).limit(limit)
		if (filterName == "onlySuccess"):
			myQuery = myQuery.where(PrintJobModel.printStatusResult == "success")
		elif (filterName == "onlyFailed"):
			myQuery = myQuery.where(PrintJobModel.printStatusResult != "success")

		if ("printStartDateTime" == sortColumn):
			if ("desc" == sortOrder):
				myQuery = myQuery.order_by(PrintJobModel.printStartDateTime.desc())
			else:
				myQuery = myQuery.order_by(PrintJobModel.printStartDateTime)
		if ("fileName" == sortColumn):
			if ("desc" == sortOrder):
				myQuery = myQuery.order_by(PrintJobModel.fileName.desc())
			else:
				myQuery = myQuery.order_by(PrintJobModel.fileName)
		return myQuery

	def loadAllPrintJobs(self):
		return PrintJobModel.select().order_by(PrintJobModel.printStartDateTime.desc())

		# return PrintJobModel.select().offset(offset).limit(limit).order_by(PrintJobModel.printStartDateTime.desc())
		# all = PrintJobModel.select().join(FilamentModel).switch(PrintJobModel).join(TemperatureModel).order_by(PrintJobModel.printStartDateTime.desc())
		# allDict = all.dicts()
		# result = prefetch(allJobsQuery, FilamentModel)
		# return result
		# return allDict

	def loadPrintJob(self, databaseId):
		return PrintJobModel.get_by_id(databaseId)

	def deletePrintJob(self, databaseId):
		with self._database.atomic() as transaction:  # Opens new transaction.
			try:
				# first delete relations
				n = FilamentModel.delete().where(FilamentModel.printJob == databaseId).execute()
				n = TemperatureModel.delete().where(TemperatureModel.printJob == databaseId).execute()

				PrintJobModel.delete_by_id(databaseId)
			except Exception as e:
				# Because this block of code is wrapped with "atomic", a
				# new transaction will begin automatically after the call
				# to rollback().
				transaction.rollback()
				self._logger.exception("Could not delete printJob from database:" + str(e))

				self.sendErrorMessageToClient("PJH-DatabaseManager", "Could not update the printjob ('"+ str(databaseId) +"') into the database. See OctoPrint.log for details!")
			pass

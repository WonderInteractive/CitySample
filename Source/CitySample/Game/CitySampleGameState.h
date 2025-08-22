// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "GameFramework/GameState.h"
#include "CitySampleGameState.generated.h"


DECLARE_DYNAMIC_MULTICAST_DELEGATE(FOnSandboxIntroStarted);
DECLARE_DYNAMIC_MULTICAST_DELEGATE(FOnSandboxIntroFinished);
DECLARE_DYNAMIC_MULTICAST_DELEGATE(FOnTestSequenceStarted);
DECLARE_DYNAMIC_MULTICAST_DELEGATE(FOnTestSequenceFinished);

DECLARE_DYNAMIC_MULTICAST_DELEGATE(FOnTriggerDaytime);
DECLARE_DYNAMIC_MULTICAST_DELEGATE(FOnTriggerNighttime);

DECLARE_DYNAMIC_MULTICAST_DELEGATE(FOnEnterPhotomode);
DECLARE_DYNAMIC_MULTICAST_DELEGATE(FOnExitPhotomode);

class ULevelSequence;

UCLASS()
class CITYSAMPLE_API ACitySampleGameState : public AGameState
{
	GENERATED_BODY()

	//////////////////////////////////////////////////////////////////////////
	// Sandbox Intro

public:
	UPROPERTY(BlueprintAssignable, BlueprintCallable)
	FOnSandboxIntroStarted OnSandboxIntroStarted;
	
	UPROPERTY(BlueprintAssignable, BlueprintCallable)
	FOnSandboxIntroFinished OnSandboxIntroFinished;

	UFUNCTION(BlueprintCallable)
	bool StartSandboxIntro();

	UFUNCTION(BlueprintCallable)
	void StopSandboxIntro();

	UFUNCTION(BlueprintPure)
	bool IsSandboxIntroPlaying() const
	{
		return bSandboxIntroPlaying;
	}

protected:
	UFUNCTION(BlueprintImplementableEvent)
	bool ReceiveStartSandboxIntro();

	UFUNCTION(BlueprintImplementableEvent)
	void ReceiveStopSandboxIntro();
	
	virtual void HandleMatchHasStarted() override;

private:
	UPROPERTY(VisibleAnywhere, Transient)
	bool bSandboxIntroPlaying = false;

	//////////////////////////////////////////////////////////////////////////
	// Test Sequence

public:
	UPROPERTY(BlueprintAssignable, BlueprintCallable)
	FOnTestSequenceStarted OnTestSequenceStarted;

	UPROPERTY(BlueprintAssignable, BlueprintCallable)
	FOnTestSequenceFinished OnTestSequenceFinished;

	UFUNCTION(BlueprintCallable)
	bool StartTestSequence();

	UFUNCTION(BlueprintCallable)
	void StopTestSequence();

	UFUNCTION(BlueprintPure)
	bool IsTestSequencePlaying() const
	{
		return bTestSequencePlaying;
	}

	UFUNCTION(BlueprintGetter)
	ULevelSequence* GetTestSequence();

    // The default test sequence. Can be overriden with the "CitySampleTest.TestSequence <asset path>" cvar
	UPROPERTY(EditAnywhere, BlueprintReadOnly, BlueprintGetter = GetTestSequence, Category = Test)
	TObjectPtr<ULevelSequence> TestSequence;

    // Store the list of possible test sequences. Required so that these are included in a cooked build
	UPROPERTY(EditAnywhere, Category = Test)
	TArray<TObjectPtr<ULevelSequence>> AvailableTestSequences;

protected:
	UFUNCTION(BlueprintImplementableEvent)
	bool ReceiveStartTestSequence();

	UFUNCTION(BlueprintImplementableEvent)
	void ReceiveStopTestSequence();

private:
	UPROPERTY(VisibleAnywhere, Transient)
	bool bTestSequencePlaying = false;

	//////////////////////////////////////////////////////////////////////////
	// GameState Events

public:
	UPROPERTY(BlueprintAssignable, BlueprintCallable)
	FOnTriggerDaytime OnTriggerDaytime;

	UPROPERTY(BlueprintAssignable, BlueprintCallable)
	FOnTriggerNighttime OnTriggerNighttime;

	UPROPERTY(BlueprintAssignable, BlueprintCallable)
	FOnEnterPhotomode OnEnterPhotomode;

	UPROPERTY(BlueprintAssignable, BlueprintCallable)
	FOnExitPhotomode OnExitPhotomode;
};
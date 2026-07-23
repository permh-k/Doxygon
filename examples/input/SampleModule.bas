Attribute VB_Name = "SampleModule"
Option Explicit
'/**!
' @file SampleModules.bas サンプルモジュール
' @brief
' Excel VBA 用のサンプルです。
'
' @warning 実行には管理者権限が必要です。
'
'
'*/

'/**!
' @fn Add 加算処理
'
' @param [in] a 値A
' @param [in] b 値B
'
' @return Add 加算結果
'*/
Public Function Add(ByVal a As Long, ByVal b As Long) As Long
    Add = a + b
End Function
